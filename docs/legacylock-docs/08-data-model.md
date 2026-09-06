# LegacyLock — Data Model

## Entity Relationship

```text
User
 │
 └── Vault
      ├── VaultMessage
      ├── Beneficiary
      ├── HeartbeatConfig
      ├── VaultStatus
      ├── NotificationLog
      └── AuditEvent
```

## User

Represents the owner identity.

Core fields:

- id
- authentication identifier
- password verifier
- created_at
- updated_at

No vault plaintext or cryptographic secrets.

## Vault

Represents a logical vault owned by a user.

Core fields:

- id
- user_id
- name/metadata
- wrapped_vmk
- vmk_crypto_version
- vmk_kdf_algorithm
- vmk_kdf_salt
- vmk_kdf_parameters
- created_at
- updated_at

MVP UX exposes one vault, but the model is not a singleton.

## VaultMessage

Stores encrypted content.

Core fields:

- id
- vault_id
- label
- ciphertext
- wrapped_mek
- crypto_version
- crypto_metadata
- created_at
- updated_at

The database contains no plaintext and no unwrapped VMK.

## Beneficiary

Core fields:

- id
- vault_id
- name
- email
- phone
- share_index
- invitation credential hash
- invitation status
- created_at
- updated_at

Raw Shamir share values are not stored.

## HeartbeatConfig

Core fields:

- vault_id
- interval
- grace_period
- last_checkin
- next_deadline
- notification configuration
- updated_at

## VaultStatus

Core fields:

- vault_id
- state: ACTIVE | GRACE | TRIGGERED
- version
- transitioned_at
- trigger_reason

The version supports optimistic concurrency.

## NotificationLog

Tracks delivery without storing secret material.

Core fields:

- id
- vault_id
- beneficiary_id
- channel
- event_type
- status
- provider_message_id
- created_at
- sent_at

## AuditEvent

Tracks security-relevant events.

Core fields:

- id
- vault_id
- actor_type
- actor_id
- event_type
- metadata
- timestamp

Audit metadata must not contain secrets or plaintext.

## Data Rules

- All vault-owned entities must be scoped by vault_id.
- All owner queries must be authorization-scoped.
- Foreign keys should be indexed.
- Destructive operations must be audited.
- Timestamps should use timezone-aware UTC values.

## VMK Persistence Semantics

`wrapped_vmk` is ciphertext produced by the client. It is not a plaintext key.

`vmk_kdf_salt` and `vmk_kdf_parameters` are non-secret metadata required for local KEK derivation.

The database must never contain the vault passphrase, KEK, or unwrapped VMK.

## Message Categorization

Each `VaultMessage` has exactly one primary `MessageCategory`.

```python
class MessageCategory(str, Enum):
    FINANCIAL = "financial"
    INSURANCE = "insurance"
    DIGITAL_ASSETS = "digital_assets"
    DIGITAL_IDENTITY = "digital_identity"
    DIGITAL_STORAGE = "digital_storage"
    DEVICES = "devices"
    ONLINE_ACCOUNTS = "online_accounts"
    PROPERTY = "property"
    DEPENDENTS = "dependents"
    BUSINESS = "business"
    PERSONAL = "personal"
```

A message MAY also contain zero or more controlled `CoverageTag` values.

```text
VaultMessage
├── category: MessageCategory
├── coverage_tags: CoverageTag[]
├── label
├── encrypted_content
├── wrapped_mek
└── timestamps
```

The MVP intentionally uses one primary category per message. Multi-topic messages should be split where practical so beneficiaries can understand individual instructions clearly.

`CoverageTag` is a controlled vocabulary validated against the selected primary category; arbitrary strings are not authoritative coverage signals.

Coverage applicability uses `UNKNOWN | APPLICABLE | NOT_APPLICABLE`. Only `APPLICABLE` domains contribute to the readiness denominator.
