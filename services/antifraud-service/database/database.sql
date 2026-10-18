--
--
--

CREATE TABLE analysis_statuses(
    id                              SERIAL PRIMARY KEY,
    enumerator                      VARCHAR(50) NOT NULL UNIQUE
);

INSERT INTO analysis_statuses (enumerator) VALUES
('APPROVED'),
('TWO_FACTOR_REQUIRED'),
('REJECTED');

CREATE TABLE risk_axes(
    id                              SERIAL PRIMARY KEY,
    enumerator                      VARCHAR(50) NOT NULL UNIQUE
);

INSERT INTO risk_axes (enumerator) VALUES
('IDENTITY'),
('TRANSACTION');

CREATE TABLE pix_transactions(
    id                              SERIAL PRIMARY KEY,
    pix_id                          VARCHAR(64) NOT NULL UNIQUE,
    request_hash                    CHAR(64) NOT NULL,
    amount_cents                    BIGINT NOT NULL CHECK (amount_cents > 0),
    transaction_date                TIMESTAMPTZ NOT NULL,
    utc_offset_minutes              INTEGER NOT NULL,
    source_branch                   VARCHAR(6) NOT NULL,
    source_account_number           VARCHAR(20) NOT NULL,
    source_opening_date             TIMESTAMPTZ NOT NULL,
    source_document                 VARCHAR(14) NOT NULL,
    destination_participant         CHAR(8) NOT NULL,
    destination_branch              VARCHAR(6) NOT NULL,
    destination_account_number      VARCHAR(20) NOT NULL,
    destination_opening_date        TIMESTAMPTZ NOT NULL,
    destination_document            VARCHAR(14) NOT NULL,
    device_id                       VARCHAR(128) NOT NULL,
    channel                         VARCHAR(32) NOT NULL,
    ip                              VARCHAR(45) NOT NULL,
    latitude                        NUMERIC(9, 6),
    longitude                       NUMERIC(9, 6),
    received_at                     TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    CHECK ((latitude IS NULL) = (longitude IS NULL))
);

CREATE INDEX pix_by_payer_time ON pix_transactions(source_document, transaction_date);
CREATE INDEX pix_by_payer_device ON pix_transactions(source_document, device_id, transaction_date);
CREATE INDEX pix_by_destination_time ON pix_transactions(
    destination_participant, destination_branch, destination_account_number, transaction_date);
CREATE INDEX pix_by_pair ON pix_transactions(source_document, destination_document);

CREATE TABLE pix_analyses(
    id                              SERIAL PRIMARY KEY,
    analysis_key                    CHAR(36) NOT NULL UNIQUE,
    pix_transaction_id              INTEGER NOT NULL UNIQUE REFERENCES pix_transactions(id),
    analysis_status_id              INTEGER NOT NULL REFERENCES analysis_statuses(id),
    identity_score                  INTEGER NOT NULL,
    transaction_score               INTEGER NOT NULL,
    decision_reason                 VARCHAR(500) NOT NULL,
    rules_version                   VARCHAR(20) NOT NULL,
    latency_ms                      NUMERIC(10, 2) NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW())
);

CREATE TABLE rule_hits(
    id                              SERIAL PRIMARY KEY,
    pix_analysis_id                 INTEGER NOT NULL REFERENCES pix_analyses(id),
    rule_code                       VARCHAR(10) NOT NULL,
    risk_axis_id                    INTEGER NOT NULL REFERENCES risk_axes(id),
    effect                          VARCHAR(20) NOT NULL CHECK (effect IN (
                                        'SCORE', 'FORCE_TWO_FACTOR', 'REJECT', 'FAILSAFE_TWO_FACTOR', 'FAILSAFE_REJECT')),
    points                          INTEGER NOT NULL,
    reason                          VARCHAR(500) NOT NULL,
    evidence                        JSONB NOT NULL
);

CREATE INDEX rule_hits_by_analysis ON rule_hits(pix_analysis_id);
