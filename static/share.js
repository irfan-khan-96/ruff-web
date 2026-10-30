(function () {
    const startBtn = document.getElementById("start-share");
    const joinBtn = document.getElementById("join-share");
    const codeEl = document.getElementById("share-code");
    const shareStatus = document.getElementById("share-status");
    const receiveStatus = document.getElementById("receive-status");
    const receiveCodeInput = document.getElementById("receive-code");

    const config = window.RUFF_SHARE || {};
    // The stash to send comes from the picker on the Pass page
    const picker = document.getElementById("share-stash");
    const syncPicker = () => { config.payloadUrl = picker ? picker.value : config.payloadUrl; payloadCache = null; };
    const socket = typeof io === "function" ? io() : null;

    let roomCode = null;
    let peerConnection = null;
    let dataChannel = null;
    let isSender = false;
    let payloadCache = null;
    picker?.addEventListener("change", syncPicker);
    // Fill the picker from this device's notes
    (async () => {
        if (!picker || !window.RuffStore) return;
        await window.RuffStore.ready;
        const notes = await window.RuffStore.list();
        for (const note of notes) {
            const option = new Option(window.RuffStore.firstLine(note.text) || "Untitled", note.id);
            option.selected = note.id === picker.dataset.selected;
            picker.append(option);
        }
        const none = document.getElementById("share-none");
        if (none) none.hidden = notes.length > 0;
        picker.hidden = notes.length === 0;
        if (startBtn) startBtn.disabled = notes.length === 0;
        syncPicker();
    })();

    function setShareStatus(text) {
        if (shareStatus) shareStatus.textContent = text;
    }

    function setReceiveStatus(text) {
        if (receiveStatus) receiveStatus.textContent = text;
    }

    function generateCode() {
        // Cryptographically random 6-character code (Math.random is guessable)
        const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
        let code = "";
        while (code.length < 6) {
            const [byte] = crypto.getRandomValues(new Uint8Array(1));
            // 252 = 7 * 36: skip higher bytes so every character is equally likely
            if (byte < 252) code += alphabet[byte % 36];
        }
        return code;
    }

    function createPeerConnection() {
        peerConnection = new RTCPeerConnection({
            iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
        });

        peerConnection.onicecandidate = (event) => {
            if (event.candidate && roomCode) {
                socket.emit("signal", {
                    room: roomCode,
                    payload: { type: "candidate", candidate: event.candidate }
                });
            }
        };

        peerConnection.ondatachannel = (event) => {
            dataChannel = event.channel;
            wireDataChannel();
        };
    }

    function wireDataChannel() {
        if (!dataChannel) return;

        dataChannel.onopen = () => {
            if (isSender) {
                setShareStatus("Connected. Sending stash…");
                sendPayload();
            } else {
                setReceiveStatus("Connected. Waiting for stash…");
            }
        };

        dataChannel.onmessage = async (event) => {
            try {
                const payload = JSON.parse(event.data);
                setReceiveStatus("Received stash. Importing…");
                await importPayload(payload);
                setReceiveStatus("Stash imported successfully.");
            } catch (err) {
                console.error(err);
                setReceiveStatus("Failed to import stash.");
            }
        };
    }

    // Notes live on the device (local-first): read the one picked to send
    async function fetchPayload() {
        if (!config.payloadUrl) {
            throw new Error("No stash selected for sharing.");
        }
        await window.RuffStore.ready;
        const note = await window.RuffStore.get(config.payloadUrl);
        if (!note) {
            throw new Error("That note isn't on this device.");
        }
        return { id: note.id, title: window.RuffStore.firstLine(note.text), body: note.text, tags: note.tags || [] };
    }

    async function sendPayload() {
        try {
            if (!payloadCache) {
                payloadCache = await fetchPayload();
            }
            dataChannel.send(JSON.stringify(payloadCache));
            setShareStatus("Stash sent.");
        } catch (err) {
            console.error(err);
            setShareStatus("Failed to send stash.");
        }
    }

    // A received note becomes a new note on this device (then syncs)
    async function importPayload(payload) {
        const body = String(payload.body || "");
        const title = String(payload.title || "").trim();
        const text = title && window.RuffStore.firstLine(body) !== title ? `${title}\n\n${body}` : body;
        if (!text.trim() || text.length > 50000) {
            throw new Error("Import failed");
        }
        const tags = (Array.isArray(payload.tags) ? payload.tags : []).map((t) => String(t).trim().toLowerCase()).filter((t) => t && t.length <= 50).slice(0, 20);
        const note = await window.RuffStore.save({ text, tags });
        await window.RuffStore.sync();
        return note;
    }

    if (!socket) {
        setShareStatus("Nearby share is unavailable right now.");
        setReceiveStatus("Nearby share is unavailable right now.");
        startBtn?.setAttribute("disabled", "disabled");
        joinBtn?.setAttribute("disabled", "disabled");
        return;
    }

    socket.on("join_refused", ({ reason } = {}) => {
        const message = reason === "room_full"
            ? "That share is already in progress with someone else."
            : "Too many attempts. Wait a minute and try again.";
        if (isSender) setShareStatus(message);
        else setReceiveStatus(message);
    });

    socket.on("signal", async (payload) => {
        if (!peerConnection) return;

        if (payload.type === "offer") {
            await peerConnection.setRemoteDescription(new RTCSessionDescription(payload.offer));
            const answer = await peerConnection.createAnswer();
            await peerConnection.setLocalDescription(answer);
            socket.emit("signal", {
                room: roomCode,
                payload: { type: "answer", answer }
            });
        }

        if (payload.type === "answer") {
            await peerConnection.setRemoteDescription(new RTCSessionDescription(payload.answer));
        }

        if (payload.type === "candidate") {
            await peerConnection.addIceCandidate(new RTCIceCandidate(payload.candidate));
        }
    });

    socket.on("peer_joined", async () => {
        if (!isSender) return;

        try {
            setShareStatus("Peer joined. Establishing connection…");
            const offer = await peerConnection.createOffer();
            await peerConnection.setLocalDescription(offer);
            socket.emit("signal", {
                room: roomCode,
                payload: { type: "offer", offer }
            });
        } catch (err) {
            console.error(err);
            setShareStatus("Failed to create offer.");
        }
    });

    startBtn?.addEventListener("click", async () => {
        try {
            if (!config.payloadUrl) {
                setShareStatus("Pick a stash to send first.");
                return;
            }
            isSender = true;
            roomCode = generateCode();
            codeEl.textContent = `Code: ${roomCode}`;
            setShareStatus("Waiting for receiver…");

            createPeerConnection();
            dataChannel = peerConnection.createDataChannel("ruff-share");
            wireDataChannel();

            socket.emit("join_room", { room: roomCode });
        } catch (err) {
            console.error(err);
            setShareStatus("Failed to start sharing.");
        }
    });

    joinBtn?.addEventListener("click", async () => {
        const code = (receiveCodeInput.value || "").trim().toUpperCase();
        if (!code) return;

        try {
            isSender = false;
            roomCode = code;
            createPeerConnection();
            socket.emit("join_room", { room: roomCode });
            setReceiveStatus("Connected to room. Waiting for offer…");

            // Receiver waits for offer
        } catch (err) {
            console.error(err);
            setReceiveStatus("Failed to join room.");
        }
    });
})();
