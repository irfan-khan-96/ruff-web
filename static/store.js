/* Ruff local store: notes live in this browser (IndexedDB) first.
   Works offline and without an account; signed-in devices sync through
   /api/sync (newest edit wins, deletions travel as tombstones). */
(function () {
    "use strict";

    const DB_NAME = "ruff";
    const NOTES = "notes";
    const META = "meta";
    const body = document.body;
    const userId = body.dataset.userId || "";
    const csrf = body.dataset.csrf || "";

    /* --- IndexedDB, with an in-memory fallback (private mode, blocked storage) --- */
    let memory = null;
    const openDb = () => new Promise((resolve) => {
        if (!("indexedDB" in window)) { resolve(null); return; }
        const request = indexedDB.open(DB_NAME, 1);
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains(NOTES)) db.createObjectStore(NOTES, { keyPath: "id" });
            if (!db.objectStoreNames.contains(META)) db.createObjectStore(META, { keyPath: "key" });
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => resolve(null);
    });
    const dbReady = openDb().then((db) => {
        if (!db) memory = { [NOTES]: new Map(), [META]: new Map() };
        return db;
    });

    const tx = async (store, mode, work) => {
        const db = await dbReady;
        if (!db) return work(null, memory[store]);
        return new Promise((resolve, reject) => {
            const t = db.transaction(store, mode);
            const result = work(t.objectStore(store), null);
            t.oncomplete = () => resolve(result && result.__value !== undefined ? result.__value : result);
            t.onerror = () => reject(t.error);
        });
    };
    const req = (request) => {
        const box = {};
        request.onsuccess = () => { box.__value = request.result; };
        return box;
    };

    const getAll = (store) => tx(store, "readonly", (os, map) => (map ? [...map.values()] : req(os.getAll())));
    const getOne = (store, key) => tx(store, "readonly", (os, map) => (map ? map.get(key) : req(os.get(key))));
    const putOne = (store, value) => tx(store, "readwrite", (os, map) => {
        if (map) map.set(value.id || value.key, value); else os.put(value);
        return value;
    });
    const clearStore = (store) => tx(store, "readwrite", (os, map) => (map ? map.clear() : os.clear()));
    const meta = {
        get: async (key) => (await getOne(META, key))?.value,
        set: (key, value) => putOne(META, { key, value }),
    };

    /* --- Notes ---------------------------------------------------------------- */
    const firstLine = (text) => {
        for (const line of (text || "").split("\n")) {
            const clean = line.replace(/^\s*(?:[-*]\s+)?\[( |x|X)\]\s?/, "").replace(/^#+/, "").trim();
            if (clean) return clean.slice(0, 200);
        }
        return "";
    };
    const tasks = (text) => (text || "").split("\n")
        .map((line) => line.match(/^\s*(?:[-*]\s+)?\[( |x|X)\]\s?(.*)$/))
        .filter((m) => m && m[2].trim())
        .map((m) => ({ text: m[2].trim(), done: m[1] !== " " }));
    const preview = (text) => {
        const lines = (text || "").split("\n").map((l) => l.trim()).filter(Boolean);
        return lines.slice(1).filter((l) => !/^(?:[-*]\s+)?\[( |x|X)\]/.test(l)).join(" ").slice(0, 160);
    };
    const newId = () => (crypto.randomUUID ? crypto.randomUUID()
        : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
            (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)));

    async function list() {
        return (await getAll(NOTES)).filter((n) => !n.deleted).sort((a, b) => b.updated_at - a.updated_at);
    }

    async function get(id) {
        const note = await getOne(NOTES, id);
        return note && !note.deleted ? note : null;
    }

    async function save(note) {
        const saved = {
            id: note.id || newId(),
            text: note.text || "",
            tags: note.tags || [],
            updated_at: Date.now(),
            deleted: false,
            dirty: true,
        };
        await putOne(NOTES, saved);
        scheduleSync();
        return saved;
    }

    async function remove(id) {
        await putOne(NOTES, { id, text: "", tags: [], updated_at: Date.now(), deleted: true, dirty: true });
        scheduleSync();
    }

    /* --- Sync --------------------------------------------------------------------- */
    let syncing = null;
    let syncTimer = null;
    const listeners = new Set();
    const emit = (state) => listeners.forEach((fn) => fn(state));

    function scheduleSync(delay = 1500) {
        if (!userId) return;
        clearTimeout(syncTimer);
        syncTimer = setTimeout(() => sync(), delay);
    }

    async function sync() {
        if (!userId) return { state: "local" };
        if (!navigator.onLine) { emit("offline"); return { state: "offline" }; }
        if (syncing) return syncing;
        syncing = (async () => {
            try {
                emit("syncing");
                const all = await getAll(NOTES);
                const dirty = all.filter((n) => n.dirty).slice(0, 500);
                const response = await fetch("/api/sync", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
                    body: JSON.stringify({
                        cursor: await meta.get("cursor") || null,
                        changes: dirty.map(({ id, text, tags, updated_at, deleted }) => ({ id, text, tags, updated_at, deleted })),
                    }),
                });
                if (response.status === 401) { emit("signed-out"); return { state: "signed-out" }; }
                if (!response.ok) { emit("error"); return { state: "error" }; }
                const data = await response.json();

                // Our changes the server took (or settled): no longer dirty, unless edited meanwhile
                const sentAt = new Map(dirty.map((n) => [n.id, n.updated_at]));
                for (const id of data.accepted) {
                    const current = await getOne(NOTES, id);
                    if (current && current.updated_at === sentAt.get(id)) {
                        if (current.deleted) await tx(NOTES, "readwrite", (os, map) => (map ? map.delete(id) : os.delete(id)));
                        else await putOne(NOTES, { ...current, dirty: false });
                    }
                }
                // Theirs: take anything newer than ours
                for (const remote of data.stashes) {
                    const local = await getOne(NOTES, remote.id);
                    if (!local || !local.dirty || remote.updated_at >= local.updated_at) {
                        await putOne(NOTES, { ...remote, deleted: false, dirty: false });
                    }
                }
                for (const id of data.deleted) {
                    const local = await getOne(NOTES, id);
                    if (local && !local.dirty) await tx(NOTES, "readwrite", (os, map) => (map ? map.delete(id) : os.delete(id)));
                }
                await meta.set("cursor", data.cursor);
                const more = all.filter((n) => n.dirty).length > dirty.length;
                emit(data.rejected.length ? "partial" : "synced");
                if (more) scheduleSync(100);
                return { state: "synced", changed: data.stashes.length + data.deleted.length, rejected: data.rejected };
            } catch (e) {
                emit("offline");
                return { state: "offline" };
            } finally {
                syncing = null;
            }
        })();
        return syncing;
    }

    /* --- Whose notes are these? ----------------------------------------------------
       Notes written signed out belong to this device; signing in adopts them into
       the account. A different account on this device starts from a clean store. */
    const ready = (async () => {
        const owner = await meta.get("owner");
        if (userId && owner && owner !== userId) {
            await clearStore(NOTES);
            await clearStore(META);
        }
        if (userId && owner !== userId) {
            for (const note of await getAll(NOTES)) await putOne(NOTES, { ...note, dirty: true });
            await meta.set("owner", userId);
            await meta.set("cursor", null);
        }
        if (userId) await sync();
    })();

    /* Signing out: send what's left, then clear this device */
    document.addEventListener("submit", async (event) => {
        const form = event.target;
        if (!form.matches("[data-signout]") || form.dataset.cleared) return;
        event.preventDefault();
        await sync();
        await clearStore(NOTES);
        await clearStore(META);
        form.dataset.cleared = "yes";
        form.submit();
    });

    window.addEventListener("online", () => scheduleSync(200));

    window.RuffStore = {
        ready, list, get, save, remove, sync, newId, firstLine, tasks, preview,
        signedIn: Boolean(userId),
        onSync: (fn) => listeners.add(fn),
    };
})();
