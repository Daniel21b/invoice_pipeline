-- Invoice Pipeline Database Schema - Phase 3
-- PostgreSQL schema for invoice data storage

-- Drop existing objects if recreating
DROP VIEW IF EXISTS invoices_by_source CASCADE;
DROP VIEW IF EXISTS verified_invoices CASCADE;
DROP TABLE IF EXISTS invoices CASCADE;

-- Create invoices table
CREATE TABLE invoices (
    id SERIAL PRIMARY KEY,

    -- Core invoice data
    invoice_number VARCHAR(50),
    vendor_name VARCHAR(255) NOT NULL,
    invoice_date DATE NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    category VARCHAR(100),

    -- Metadata (crucial for tracking source)
    source_type VARCHAR(50) NOT NULL, -- 'pdf_scan', 'excel_bulk', 'manual_entry'
    source_file VARCHAR(255), -- S3 key for PDFs, filename for Excel, 'manual' for forms
    extraction_confidence FLOAT, -- 0-100 for PDFs, NULL for others

    -- Timestamps
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100), -- User who uploaded
    notes TEXT,

    -- For Phase 4: Audit trail
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    is_deleted BOOLEAN DEFAULT FALSE,

    -- Classification & Soft Delete (Phase 8)
    transaction_type VARCHAR(10) CHECK (transaction_type IN ('INCOME', 'EXPENSE')),
    deleted_at TIMESTAMP,
    deletion_reason TEXT
);

-- Create indexes for fast queries
CREATE INDEX idx_invoices_vendor_name ON invoices(vendor_name);
CREATE INDEX idx_invoices_invoice_date ON invoices(invoice_date);
CREATE INDEX idx_invoices_source_type ON invoices(source_type);
CREATE INDEX idx_invoices_ingested_at ON invoices(ingested_at);
CREATE INDEX idx_invoices_invoice_number ON invoices(invoice_number);
CREATE INDEX idx_invoices_category ON invoices(category);

-- Partial index for non-deleted records (common query pattern)
CREATE INDEX idx_invoices_active ON invoices(id) WHERE is_deleted = FALSE;

-- Index for transaction type (income/expense classification)
CREATE INDEX idx_invoices_transaction_type ON invoices(transaction_type);

-- Phase 5: Additional indexes for query optimization
-- Index on ingested_at DESC (for date range filtering and sorting)
CREATE INDEX idx_invoices_ingested_at_desc ON invoices(ingested_at DESC);

-- Composite index (vendor + date) for vendor-based date range queries
CREATE INDEX idx_invoices_vendor_date ON invoices(vendor_name, invoice_date);

-- Index on amount (for sum/aggregation queries)
CREATE INDEX idx_invoices_amount ON invoices(amount);

-- Create a view for "verified" data (PDFs with high confidence only)
CREATE VIEW verified_invoices AS
SELECT
    id,
    invoice_number,
    vendor_name,
    invoice_date,
    amount,
    category,
    source_type,
    source_file,
    extraction_confidence,
    ingested_at,
    created_by,
    notes
FROM invoices
WHERE source_type = 'pdf_scan'
  AND extraction_confidence >= 70
  AND is_deleted = FALSE;

-- Create a view for reporting by source
CREATE VIEW invoices_by_source AS
SELECT
    source_type,
    COUNT(*) as count,
    SUM(amount) as total_amount,
    AVG(amount) as avg_amount,
    MIN(amount) as min_amount,
    MAX(amount) as max_amount,
    MIN(ingested_at) as first_at,
    MAX(ingested_at) as last_at
FROM invoices
WHERE is_deleted = FALSE
GROUP BY source_type;

-- Create a function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to auto-update updated_at on row changes
CREATE TRIGGER update_invoices_updated_at
    BEFORE UPDATE ON invoices
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Insert sample data for testing (optional - can be removed in production)
-- INSERT INTO invoices (invoice_number, vendor_name, invoice_date, amount, category, source_type, source_file, extraction_confidence, created_by)
-- VALUES
--     ('INV-001', 'Acme Corp', '2024-01-15', 1500.00, 'Inventory', 'pdf_scan', 'invoices/sample1.pdf', 95.5, 'system'),
--     ('INV-002', 'Office Supplies Inc', '2024-01-16', 250.00, 'Supplies', 'excel_bulk', 'bulk_upload.xlsx', NULL, 'admin'),
--     ('INV-003', 'Tech Solutions', '2024-01-17', 3000.00, 'Services', 'manual_entry', 'manual', NULL, 'john.doe');

-- ============================================================
-- Phase 6: Analytics Tables
-- Pre-calculated summaries for fast dashboard queries
-- ============================================================

-- Monthly summary (pre-calculated for fast dashboards)
CREATE TABLE IF NOT EXISTS invoice_summary_monthly (
    year INT NOT NULL,
    month INT NOT NULL,
    total_amount DECIMAL(12,2),
    total_count INT,
    source_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (year, month, source_type)
);

-- Category breakdown
CREATE TABLE IF NOT EXISTS invoice_summary_category (
    category VARCHAR(100) NOT NULL,
    total_amount DECIMAL(12,2),
    total_count INT,
    avg_amount DECIMAL(12,2),
    source_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (category, source_type)
);

-- Vendor breakdown
CREATE TABLE IF NOT EXISTS invoice_summary_vendor (
    vendor VARCHAR(255) NOT NULL,
    total_amount DECIMAL(12,2),
    total_count INT,
    avg_amount DECIMAL(12,2),
    last_invoice_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (vendor)
);

-- Data quality metrics
CREATE TABLE IF NOT EXISTS invoice_quality_metrics (
    date DATE NOT NULL,
    total_invoices INT,
    verified_invoices INT,
    unverified_invoices INT,
    avg_processing_time_ms INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date)
);

-- Create indexes for fast analytics queries
CREATE INDEX IF NOT EXISTS idx_summary_monthly_year_month ON invoice_summary_monthly(year, month);
CREATE INDEX IF NOT EXISTS idx_summary_category_category ON invoice_summary_category(category);
CREATE INDEX IF NOT EXISTS idx_summary_vendor_vendor ON invoice_summary_vendor(vendor);
CREATE INDEX IF NOT EXISTS idx_quality_metrics_date ON invoice_quality_metrics(date);

-- Grant permissions (adjust as needed for your RDS setup)
-- GRANT SELECT, INSERT, UPDATE ON invoices TO app_user;
-- GRANT SELECT ON verified_invoices TO app_user;
-- GRANT SELECT ON invoices_by_source TO app_user;
-- GRANT USAGE, SELECT ON SEQUENCE invoices_id_seq TO app_user;

-- ============================================================
-- Phase 7: User Management & Audit Logging
-- Authentication, role-based access control, and audit trail
-- ============================================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,  -- admin, accountant, operator
    is_active BOOLEAN DEFAULT TRUE,
    company_id INT,  -- For multi-tenant support (Phase 8)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

-- Roles table (for RBAC)
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    description VARCHAR(255),
    permissions TEXT[],  -- Array of permission strings
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit log - track ALL changes
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    action VARCHAR(100) NOT NULL,  -- insert, update, delete, download, export, login, logout
    entity_type VARCHAR(50),  -- invoice, user, settings
    entity_id INT,
    details JSONB,  -- {"old_value": {...}, "new_value": {...}}
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Session tracking (for security)
CREATE TABLE IF NOT EXISTS user_sessions (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    session_token VARCHAR(255) UNIQUE NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default roles
INSERT INTO roles (name, description, permissions) VALUES
    ('admin', 'Full access to everything', ARRAY['read_all', 'write_all', 'delete_all', 'manage_users', 'view_audit']),
    ('accountant', 'View and export reports', ARRAY['read_invoices', 'export_reports', 'view_dashboard']),
    ('operator', 'Upload and process invoices', ARRAY['read_invoices', 'create_invoices', 'view_dashboard'])
ON CONFLICT (name) DO NOTHING;

-- Create indexes for Phase 7 tables
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at);

-- Trigger to update updated_at on users table
CREATE OR REPLACE FUNCTION update_users_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_users_updated_at();

-- ============================================================
-- MIGRATION: Run this on existing databases to add new columns
-- ============================================================
-- ALTER TABLE invoices
--     ADD COLUMN IF NOT EXISTS transaction_type VARCHAR(10) CHECK (transaction_type IN ('INCOME', 'EXPENSE')),
--     ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP,
--     ADD COLUMN IF NOT EXISTS deletion_reason TEXT;
-- CREATE INDEX IF NOT EXISTS idx_invoices_transaction_type ON invoices(transaction_type);
