#  LegacyLock — Zero-Knowledge Digital Legacy Vault

LegacyLock is a **user-facing, security-first web application** that allows users to securely store sensitive messages and ensure they are released only under predefined conditions (e.g., prolonged inactivity). The system is designed around **zero-knowledge principles**, meaning the server and database can never read user data.

This project focuses on **correct cryptographic boundaries, system design, and reliability**, rather than UI polish.

---

##  Key Features

*  **Client-side encryption (AES-256-GCM)**
  All messages are encrypted in the browser before being sent to the backend.

*  **Zero-knowledge backend**
  The server stores only encrypted blobs and never sees plaintext or passwords.

*  **Separable encrypted messages**
  Each vault contains multiple independently encrypted messages (not a single monolithic blob).

*  **Persistent storage**
  Encrypted messages are stored in a SQLite database and survive server restarts.

*  **No password recovery by design**
  If the user loses their password, the data is cryptographically unrecoverable.

---

## Core Design Principles

* **Zero Trust**: The backend is treated as untrusted.
* **Client Ownership**: Encryption, decryption, and key derivation happen only in the browser.
* **Minimal Attack Surface**: No crypto logic on the server.
* **Explicit Scope**: The app is not a legal will or file-hosting service.

---

##  Architecture Overview

```
Browser (Next.js)
  ├─ Encrypts message using password
  ├─ Sends ciphertext to backend
  └─ Decrypts ciphertext after retrieval

Backend (FastAPI)
  ├─ Stores encrypted blobs
  ├─ Handles message metadata
  └─ Never sees plaintext or keys

Database (SQLite)
  └─ Persists encrypted_content only
```

---

##  Project Structure

```
legacylock/
├── frontend/          # Next.js frontend
│   ├── app/
│   ├── lib/crypto.ts  # Client-side encryption logic
│   └── package.json
│
├── backend/           # FastAPI backend
│   ├── main.py
│   ├── database.py
│   └── venv/
│
├── .gitignore
└── README.md
```

---

##  Cryptography Details

* **Algorithm**: AES-256-GCM
* **Key Derivation**: PBKDF2 (SHA-256, 100k iterations)
* **IV**: Random per message
* **Key Storage**: Never stored, derived from password in-browser

Each message is encrypted independently, ensuring:

* reduced blast radius
* no ciphertext reuse
* proper authenticated encryption

---

##  Explicit Limitations (By Design)

* No password reset or recovery
* No legal enforcement (not a legal will)
* No large media files
* No server-side encryption
* No automatic death verification (heartbeat logic planned)

These constraints are intentional to preserve correctness and security.

---

##  Local Development

### Backend

```bash
cd backend
venv\Scripts\activate
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

##  Project Status

### ✅ Completed

* Full-stack integration
* Database persistence
* Separable messages
* Client-side encryption
* Zero-knowledge verification (DB inspection)

### Planned

* Key sharding (Shamir’s Secret Sharing)
* Heartbeat / inactivity detection
* Grace period & trigger logic
* Beneficiary access flow
* Deployment

---

## Why This Project Matters

LegacyLock demonstrates:

* real-world cryptographic boundaries
* secure system design
* thoughtful scope management
* end-to-end full-stack engineering

It is intentionally **industry-aligned** rather than feature-heavy.

---

## Disclaimer

LegacyLock is a **technical proof-of-concept**.
It does **not** replace legal estate planning tools and should not be used as a legal will.

---
