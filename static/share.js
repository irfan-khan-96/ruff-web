(function () {
    const startBtn = document.getElementById("start-share");
    const joinBtn = document.getElementById("join-share");
    const codeEl = document.getElementById("share-code");
    const shareStatus = document.getElementById("share-status");
    const receiveStatus = document.getElementById("receive-status");
    const receiveCodeInput = document.getElementById("receive-code");

    const config = window.RUFF_SHARE || {};
    const socket = typeof io === "function" ? io() : null;

    let roomCode = null;
    let peerConnection = null;
    let dataChannel = null;
    let isSender = false;
    let payloadCache = null;

    function setShareStatus(text) {
        if (shareStatus) shareStatus.textContent = text;
    }

    function setReceiveStatus(text) {
        if (receiveStatus) receiveStatus.textContent = text;
    }

    function generateCode() {
        return Math.random().toString(36).slice(2, 8).toUpperCase();
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

    async function fetchPayload() {
        if (!config.payloadUrl) {
            throw new Error("No stash selected for sharing.");
        }
        const res = await fetch(config.payloadUrl);
        if (!res.ok) {
            throw new Error("Failed to load stash payload.");
        }
        return res.json();
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

    async function importPayload(payload) {
        const res = await fetch(config.importUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": config.csrfToken
            },
            body: JSON.stringify(payload)
        });
        if (!res.ok) {
            throw new Error("Import failed");
        }
        return res.json();
    }

    if (!socket) {
        setShareStatus("Nearby share is unavailable right now.");
        setReceiveStatus("Nearby share is unavailable right now.");
        startBtn?.setAttribute("disabled", "disabled");
        joinBtn?.setAttribute("disabled", "disabled");
        return;
    }

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
                setShareStatus("Open a stash first, then choose Nearby Share.");
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
