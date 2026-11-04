"use client";

// Vault message CRUD — encrypts locally before POST, decrypts locally after GET.
import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  Eye,
  KeyRound,
  Lock,
  Mail,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { assertEpoch, bindVault, currentEpoch, materialRevision, decrypt as decryptWithSession, encrypt as encryptWithSession, unlockVault } from "../../lib/crypto-session";
import {
  createMessage,
  deleteMessage,
  getCryptoMaterial,
  getMessage,
  getMe,
  getVaultStatus,
  ivOf,
  listMessages,
  MESSAGE_CATEGORIES,
  type MessageMeta,
} from "../../lib/client";
import { useVault } from "../../lib/store/vault-context";
import { CopyButton, EmptyState, Modal, Spinner } from "../../components/ui";
import { EncryptionNotice } from "../../components/security";
import { useToast } from "../../components/toast";

function categoryLabel(c: string): string {
  return c.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

function SecretViewer({ label, text, onClose }: { label: string; text: string; onClose: () => void }) {
  const [revealed, setRevealed] = useState(false);
  const [locked, _setLocked] = useState(false);
  if (locked) {
    return (
      <Modal title={label} onClose={onClose}>
        <div className="flex flex-col items-center gap-3 py-6 text-center">
          <Lock className="h-8 w-8 text-muted" />
          <p className="text-sm text-muted">Secret locked.</p>
          <button type="button" className="btn-ghost text-sm" onClick={onClose}>Close</button>
        </div>
      </Modal>
    );
  }
  if (!revealed) {
    return (
      <Modal title={label} onClose={onClose}>
        <div className="flex flex-col items-center gap-3 py-4 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-raised">
            <Lock className="h-5 w-5 text-accent" />
          </span>
          <p className="text-sm font-medium">Encrypted locally</p>
          <p className="max-w-xs text-sm leading-relaxed text-muted">
            This message will be decrypted only in your current browser session.
          </p>
          <button type="button" className="btn-primary mt-2 w-full" onClick={() => setRevealed(true)}>
            <Eye className="h-4 w-4" />
            Reveal secret
          </button>
        </div>
      </Modal>
    );
  }
  return (
    <Modal title={label} onClose={onClose} wide>
      <p className="mb-2 flex items-center gap-1.5 text-xs text-success">
        <Lock className="h-3.5 w-3.5" />
        decrypted locally ✓
      </p>
      <pre className="whitespace-pre-wrap rounded-xl bg-raised p-4 text-sm leading-relaxed">{text}</pre>
      <div className="mt-3 flex justify-end gap-2">
        <CopyButton text={text} label="Copy" />
        <button type="button" className="btn-ghost text-sm" onClick={onClose}>
          <Lock className="h-3.5 w-3.5" />
          Lock
        </button>
      </div>
    </Modal>
  );
}

export default function VaultPage() {
  const { unlocked } = useVault();
  const { notify } = useToast();
  const [passphrase, setPassphrase] = useState("");
  const [showUnlockForm, setShowUnlockForm] = useState(false);
  const [unlocking, setUnlocking] = useState(false);
  const [released, setReleased] = useState(false);
  const [hasMore, setHasMore] = useState(false);
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

  async function refresh(beforeId?:number) {
    const epoch=currentEpoch();
    setLoadingList(true);
    try {
      const [rows,status]=await Promise.all([listMessages(beforeId),getVaultStatus()]);
      assertEpoch(epoch);
      setReleased(status.status === "triggered");
      setMessages(old=>beforeId?[...old,...rows]:rows);
      setHasMore(rows.length === 50);
    } finally {
      setLoadingList(false);
    }
  }

  async function unlock() {
    setErr("");
    setUnlocking(true);
    try {
      const before = currentEpoch();
      const mat = await getCryptoMaterial();
      const me = await getMe();
      assertEpoch(before);
      bindVault(`owner:${me.id}`, mat.material_revision);
      if (!mat.wrapped_vmk) {
        throw new Error("No vault yet — set one up first.");
      }
      if (!mat.vmk_kdf_salt || !mat.vmk_kdf_parameters) throw new Error("Stored wrapping metadata is incomplete. Preserve your backup and contact support.");
      await unlockVault(passphrase, {
        wrapped_vmk_b64: mat.wrapped_vmk,
        vmk_crypto_version: mat.vmk_crypto_version ?? 0,
        vmk_kdf_algorithm: mat.vmk_kdf_algorithm as "PBKDF2-SHA256",
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
      const before = currentEpoch();
      const revision = materialRevision();
      const payload = await encryptWithSession(body);
      assertEpoch(before);
      await createMessage({
        material_revision: revision,
        label: label.trim(),
        ciphertext: payload.ciphertext_b64,
        wrapped_mek: payload.wrapped_mek_b64,
        crypto_metadata: { iv: payload.iv_b64, v: payload.v },
        category,
        coverage_tags: [],
      });
      assertEpoch(before);
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
      const before=currentEpoch();
      const m = await getMessage(id);
      assertEpoch(before);
      const text = await decryptWithSession(
        { v: m.crypto_version, algo: "AES-256-GCM", kdf: null, iv_b64: ivOf(m.crypto_metadata), wrapped_mek_b64: m.wrapped_mek, ciphertext_b64: m.ciphertext },
      );
      assertEpoch(before);
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
    else { setOpened(null); setMessages([]); setBody(""); setLabel(""); setPassphrase(""); setShowForm(false); }
  }, [unlocked]);

  const filtered = useMemo(
    () => messages.filter((m) => m.label.toLowerCase().includes(query.toLowerCase())),
    [messages, query],
  );

  const grouped = useMemo(() => {
    const map = new Map<string, MessageMeta[]>();
    for (const m of filtered) {
      // List metadata carries no category; group under Personal until the
      // list endpoint exposes it (detail does). Keeps archive IA ready.
      const c = ((m as { category?: string | null }).category ?? "personal").toLowerCase();
      if (!map.has(c)) map.set(c, []);
      map.get(c)!.push(m);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [filtered]);

  if (!unlocked) {
    return (
      <main className="mx-auto max-w-md px-4 py-10">
        <div className="surface-lg flex flex-col items-center gap-3 py-10 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-raised">
            <Lock className="h-6 w-6 text-accent" />
          </span>
          <h1 className="text-xl font-semibold tracking-tight">Vault locked</h1>
          <p className="max-w-xs text-sm leading-relaxed text-muted">Your secrets are protected.</p>
          {!showUnlockForm ? (
            <button type="button" className="btn-primary mt-2 w-full" onClick={() => setShowUnlockForm(true)}>
              <KeyRound className="h-4 w-4" />
              Unlock vault
            </button>
          ) : (
            <div className="mt-2 flex w-full flex-col gap-3 text-left">
              <EncryptionNotice />
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
                  {err}
                </p>
              )}
              <button type="button" className="btn-primary w-full" disabled={unlocking} onClick={unlock}>
                <Lock className="h-4 w-4" />
                {unlocking ? "Unlocking…" : "Unlock"}
              </button>
            </div>
          )}
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="page-title">Your Vault</h1>
          <p className="supporting mt-1">{messages.length} loaded {messages.length === 1 ? "message" : "messages"} · Encrypted storage</p>
        </div>
        <button type="button" className="btn-primary ml-auto text-sm" disabled={released} onClick={() => {setShowForm((v) => !v);setBody("");setLabel("");}}>
          {showForm ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          {showForm ? "Close" : "New secret"}
        </button>
      </div>

      {released && <p className="mb-4 text-sm text-muted">This vault has been released. New secrets and key changes are disabled; existing secrets can be read or deleted.</p>}
      {showForm && !released && (
        <div className="surface-lg mb-6 flex flex-col gap-3">
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
                    <option key={c} value={c}>{categoryLabel(c)}</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
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
          <EncryptionNotice />
          <div>
            <button type="button" className="btn-primary text-sm" disabled={saving} onClick={onCreate}>
              {saving && <Spinner />}
              {saving ? "Encrypting…" : "Encrypt and save"}
            </button>
          </div>
        </div>
      )}

      {messages.length > 3 && (
        <div className="relative mb-5">
          <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
          <input
            className="input pl-10"
            placeholder="Search messages…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search messages"
          />
        </div>
      )}

      {err && <p role="alert" className="mb-4 text-sm text-danger">{err}</p>}

      {loadingList ? (
        <div className="surface-lg flex items-center gap-2 text-sm text-muted" aria-busy="true" aria-label="Loading messages">
          <Spinner />
          Loading messages…
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Mail className="h-6 w-6" />}
          title={messages.length === 0 ? "No secrets yet" : "No matches"}
          hint={messages.length === 0 ? "Create your first encrypted message. Aim for three to cover the essentials." : "Try a different search."}
        />
      ) : (
        <div className="flex flex-col gap-6">
          {grouped.map(([cat, items]) => (
            <section key={cat} aria-label={categoryLabel(cat)}>
              <p className="eyebrow mb-2 px-1">{categoryLabel(cat)}</p>
              <ul className="overflow-hidden rounded-2xl border border-border bg-surface">
                {items.map((m) => (
                  <li key={m.id} className="row-item">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-raised text-accent" aria-hidden="true">
                      ✦
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{m.label}</p>
                      <p className="mt-0.5 text-xs text-faint">
                        Added {new Date(m.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })} · 🔒 Encrypted
                      </p>
                    </div>
                    <button
                      type="button"
                      className="shrink-0 px-2 py-1 text-xs font-medium text-muted transition-colors hover:text-text"
                      disabled={openingId === m.id}
                      onClick={() => onOpen(m.id)}
                    >
                      {openingId === m.id ? <Spinner /> : "Open →"}
                    </button>
                    <button
                      type="button"
                      className="shrink-0 rounded-lg p-1.5 text-faint transition-colors hover:bg-raised hover:text-text"
                      aria-label={`Delete ${m.label}`}
                      title="Delete"
                      onClick={() => onDelete(m.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      {hasMore && <button className="btn-ghost mt-4" disabled={loadingList} onClick={()=>refresh(messages[messages.length-1]?.id).catch(e=>setErr(e.message))}>Load more messages</button>}
      {opened && (
        <SecretViewer label={opened.label} text={opened.text} onClose={() => setOpened(null)} />
      )}
    </main>
  );
}
