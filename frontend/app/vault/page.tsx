"use client";

// Vault message CRUD — encrypts locally before POST, decrypts locally after GET.
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  Eye,
  KeyRound,
  Lock,
  Mail,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { CRYPTO_VERSION, decrypt as decryptWithSession, encrypt as encryptWithSession, unlockVault } from "../../lib/crypto-session";
import {
  createMessage,
  deleteMessage,
  getCryptoMaterial,
  getMessage,
  ivOf,
  listMessages,
  MESSAGE_CATEGORIES,
  type MessageMeta,
} from "../../lib/client";
import { useVault } from "../../lib/store/vault-context";
import { CopyButton, EmptyState, Modal, Spinner } from "../../components/ui";
import { useToast } from "../../components/toast";

export default function VaultPage() {
  const { unlocked } = useVault();
  const { notify } = useToast();
  const [passphrase, setPassphrase] = useState("");
  const [unlocking, setUnlocking] = useState(false);
  const [messages, setMessages] = useState<MessageMeta[]>([]);
  const [query, setQuery] = useState("");
  const [label, setLabel] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<string>("personal");
  const [saving, setSaving] = useState(false);
  const [opened, setOpened] = useState<{ label: string; text: string } | null>(null);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [err, setErr] = useState("");

  async function refresh() {
    setLoadingList(true);
    try {
      setMessages(await listMessages());
    } finally {
      setLoadingList(false);
    }
  }

  async function unlock() {
    setErr("");
    setUnlocking(true);
    try {
      const mat = await getCryptoMaterial();
      if (!mat.wrapped_vmk || !mat.vmk_kdf_salt || !mat.vmk_kdf_parameters) {
        throw new Error("No vault yet — set one up first.");
      }
      await unlockVault(passphrase, {
        wrapped_vmk_b64: mat.wrapped_vmk,
        vmk_crypto_version: CRYPTO_VERSION,
        vmk_kdf_algorithm: "PBKDF2-SHA256",
        vmk_kdf_salt_b64: mat.vmk_kdf_salt,
        vmk_kdf_parameters: mat.vmk_kdf_parameters,
      });
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Unlock failed");
    } finally {
      // Always drop the passphrase from memory-backed state, success or not.
      setPassphrase("");
      setUnlocking(false);
    }
  }

  async function onCreate() {
    setErr("");
    setSaving(true);
    try {
      if (!label.trim() || !body.trim()) throw new Error("Label and secret text are required.");
      const payload = await encryptWithSession(body);
      await createMessage({
        label: label.trim(),
        ciphertext: payload.ciphertext_b64,
        wrapped_mek: payload.wrapped_mek_b64,
        crypto_metadata: { iv: payload.iv_b64, v: payload.v },
        category,
        coverage_tags: [],
      });
      setLabel("");
      setBody("");
      setShowForm(false);
      await refresh();
      notify("success", "Message encrypted and saved.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Create failed");
    } finally {
      setSaving(false);
    }
  }

  async function onOpen(id: number) {
    setErr("");
    setOpeningId(id);
    try {
      const m = await getMessage(id);
      const text = await decryptWithSession(
        { v: m.crypto_version, algo: "AES-256-GCM", kdf: null, iv_b64: ivOf(m.crypto_metadata), wrapped_mek_b64: m.wrapped_mek, ciphertext_b64: m.ciphertext },
      );
      setOpened({ label: m.label, text });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Decrypt failed");
    } finally {
      setOpeningId(null);
    }
  }

  async function onDelete(id: number) {
    if (!window.confirm("Delete this encrypted message? This cannot be undone.")) return;
    try {
      await deleteMessage(id);
      await refresh();
      notify("success", "Message deleted.");
    } catch {
      notify("error", "Delete failed.");
    }
  }

  useEffect(() => {
    if (unlocked) refresh().catch(() => {});
  }, [unlocked]);

  const filtered = useMemo(
    () => messages.filter((m) => m.label.toLowerCase().includes(query.toLowerCase())),
    [messages, query],
  );

  if (!unlocked) {
    return (
      <main className="mx-auto max-w-md px-4 py-10">
        <div className="card flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-accent" />
            <h1 className="text-xl font-semibold">Unlock vault</h1>
          </div>
          <p className="text-sm text-muted">
            Enter your vault passphrase. The wrapped key is fetched and unwrapped in this
            tab only — your passphrase never leaves the browser.
          </p>
          <div>
            <label className="label" htmlFor="unlock-pass">Vault passphrase</label>
            <input
              id="unlock-pass"
              type="password"
              className="input"
              autoComplete="current-password"
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && unlock()}
            />
          </div>
          {err && (
            <p role="alert" className="text-sm text-danger">
              {err} <Link href="/vault/setup" className="underline">Set up a vault instead</Link>
            </p>
          )}
          <button type="button" className="btn-primary w-full" disabled={unlocking} onClick={unlock}>
            <Lock className="h-4 w-4" />
            {unlocking ? "Unlocking…" : "Unlock"}
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold">Vault</h1>
        <span className="chip">{messages.length} messages</span>
        <button type="button" className="btn-primary ml-auto text-sm" onClick={() => setShowForm((v) => !v)}>
          <Plus className="h-4 w-4" />
          New message
        </button>
      </div>

      {showForm && (
        <div className="card mb-6 flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="msg-label">Label</label>
              <input
                id="msg-label"
                className="input"
                placeholder="e.g. Bank credentials"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="msg-cat">Category</label>
              <div className="relative">
                <select
                  id="msg-cat"
                  className="input appearance-none pr-8"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
                  {MESSAGE_CATEGORIES.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
              </div>
            </div>
          </div>
          <div>
            <label className="label" htmlFor="msg-body">Secret text</label>
            <textarea
              id="msg-body"
              className="input min-h-28"
              rows={4}
              placeholder="Write the secret…"
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </div>
          <p className="flex items-center gap-1.5 text-xs text-faint">
            <ShieldCheck className="h-3.5 w-3.5 text-success" />
            Encrypted in this tab before upload. The server stores ciphertext only.
          </p>
          <div>
            <button type="button" className="btn-primary text-sm" disabled={saving} onClick={onCreate}>
              {saving && <Spinner />}
              {saving ? "Encrypting…" : "Encrypt and save"}
            </button>
          </div>
        </div>
      )}

      {messages.length > 3 && (
        <div className="relative mb-4">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
          <input
            className="input pl-9"
            placeholder="Search messages…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search messages"
          />
        </div>
      )}

      {err && <p role="alert" className="mb-4 text-sm text-danger">{err}</p>}

      {loadingList ? (
        <div className="card flex items-center gap-2 text-sm text-muted" aria-busy="true" aria-label="Loading messages">
          <Spinner />
          Loading messages…
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Mail className="h-8 w-8" />}
          title={messages.length === 0 ? "No messages yet" : "No matches"}
          hint={messages.length === 0 ? "Create your first encrypted message above. Aim for three to cover the essentials." : "Try a different search."}
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {filtered.map((m) => (
            <li key={m.id} className="card flex items-center gap-3 !p-3">
              <Mail className="h-4 w-4 shrink-0 text-muted" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{m.label}</p>
                <p className="text-xs text-faint">{new Date(m.created_at).toLocaleString()}</p>
              </div>
              <button
                type="button"
                className="btn-ghost px-2 py-1 text-xs"
                disabled={openingId === m.id}
                onClick={() => onOpen(m.id)}
              >
                {openingId === m.id ? <Spinner /> : <Eye className="h-3.5 w-3.5" />}
                Decrypt
              </button>
              <button
                type="button"
                className="btn-ghost px-2 py-1 text-xs"
                aria-label={`Delete ${m.label}`}
                title="Delete"
                onClick={() => onDelete(m.id)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {opened && (
        <Modal title={opened.label} onClose={() => setOpened(null)} wide>
          <pre className="whitespace-pre-wrap rounded-md bg-raised p-4 text-sm">{opened.text}</pre>
          <div className="mt-3 flex justify-end gap-2">
            <CopyButton text={opened.text} label="Copy text" />
            <button type="button" className="btn-ghost text-sm" onClick={() => setOpened(null)}>
              Close
            </button>
          </div>
        </Modal>
      )}
    </main>
  );
}
