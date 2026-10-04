// The live room. The video goes browser to browser (WebRTC); this server only relays the setup
// messages and the chat. Everything shown is inserted as text, never parsed as markup.
document.addEventListener("DOMContentLoaded", () => {
  const room = document.getElementById("room");
  if (!room) return;

  const $ = (id) => document.getElementById(id);
  const requestId = Number(room.dataset.requestId);
  const backUrl = room.dataset.backUrl;
  const socket = io();   
  window.roomSocket = socket;                           // shared with the whiteboard and files scripts                               // same origin only
  const remoteStream = new MediaStream();
  let pc = null, pending = [], iceServers = [], myRole = "", joined = false;
  let camTrack = null, micTrack = null, screenTrack = null;

  function setStatus(text, kind) {
    $("roomStatus").textContent = text;
    $("roomStatus").className = "flash flash-" + (kind || "info");
  }
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // ---------- camera and microphone ----------
  function showLocal(track) {
    $("localVideo").srcObject = new MediaStream(track ? [track] : []);
  }
  function updateButtons() {
    $("btnMic").disabled = !micTrack;
    $("btnCam").disabled = !camTrack;
    $("btnScreen").disabled = !(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia);
  }
  async function startMedia() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      $("mediaNote").textContent =
        "Camera and microphone need a secure page (HTTPS or localhost). Chat still works.";
      updateButtons();
      return;
    }
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    } catch (first) {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        $("mediaNote").textContent = "The camera is unavailable, so you are audio only.";
      } catch (second) {
        $("mediaNote").textContent = "Could not use the camera or microphone (permission denied, or " +
          "another app is using them). You can still chat and watch.";
      }
    }
    if (stream) {
      camTrack = stream.getVideoTracks()[0] || null;
      micTrack = stream.getAudioTracks()[0] || null;
      showLocal(camTrack);
    }
    updateButtons();
  }

  // ---------- the peer connection ----------
  function closePeer() {
    if (pc) { pc.onicecandidate = pc.ontrack = pc.onconnectionstatechange = null; pc.close(); pc = null; }
    remoteStream.getTracks().forEach((t) => remoteStream.removeTrack(t));
    $("remoteVideo").srcObject = null;
    pending = [];
  }
  function newPeer() {
    closePeer();
    pc = new RTCPeerConnection({ iceServers });
    pc.onicecandidate = (e) => {
      if (e.candidate) socket.emit("signal", { type: "candidate", data: e.candidate.toJSON() });
    };
    pc.ontrack = (e) => { remoteStream.addTrack(e.track); $("remoteVideo").srcObject = remoteStream; };
    pc.onconnectionstatechange = () => {
      const state = pc ? pc.connectionState : "";
      if (state === "connected") setStatus("Connected. You are in the session.", "success");
      else if (state === "disconnected") setStatus("The connection was interrupted. Trying to recover…", "info");
      else if (state === "failed") setStatus("The video connection failed. This can happen between some networks " +
        "unless the server has a TURN relay configured. Chat still works.", "error");
    };
  }
  function attachLocal() {
    if (!pc) return Promise.resolve();
    return Promise.all(pc.getTransceivers().map((tx) => {
      const kind = tx.receiver.track.kind;
      const track = kind === "video" ? (screenTrack || camTrack) : micTrack;
      if (track) tx.direction = "sendrecv";
      return tx.sender.replaceTrack(track || null).catch(() => {});
    }));
  }
  async function flushPending() {
    const list = pending;
    pending = [];
    for (const c of list) { try { await pc.addIceCandidate(c); } catch (_) { /* ignore */ } }
  }
  async function makeOffer() {
    newPeer();
    pc.addTransceiver("audio", { direction: "sendrecv" });
    pc.addTransceiver("video", { direction: "sendrecv" });
    await attachLocal();
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    socket.emit("signal", { type: "offer", data: { type: "offer", sdp: pc.localDescription.sdp } });
  }

  // ---------- messages from the server ----------
  socket.on("connect", async () => {
    await mediaReady;
    socket.emit("join", { request_id: requestId });
  });
  socket.on("joined", (info) => {
    joined = true;
    myRole = info.role;
    iceServers = info.ice_servers || [];
    info.messages.forEach((m) => addChat(m));
    setStatus(info.peer_present ? "The other person is here. Connecting…"
                                : "Waiting for the other person to join…", "info");
  });
  socket.on("peer_joined", async () => {
    setStatus("The other person joined. Connecting…", "info");
    try { await makeOffer(); } catch (err) { setStatus("Could not start the video connection.", "error"); }
  });
  socket.on("signal", async (msg) => {
    try {
      if (msg.type === "offer") {
        newPeer();
        await pc.setRemoteDescription(msg.data);
        await attachLocal();
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        socket.emit("signal", { type: "answer", data: { type: "answer", sdp: pc.localDescription.sdp } });
        await flushPending();
      } else if (msg.type === "answer" && pc) {
        await pc.setRemoteDescription(msg.data);
        await flushPending();
      } else if (msg.type === "candidate") {
        if (pc && pc.remoteDescription) { try { await pc.addIceCandidate(msg.data); } catch (_) { /* ignore */ } }
        else pending.push(msg.data);
      }
    } catch (err) {
      setStatus("Could not set up the video connection.", "error");
    }
  });
  socket.on("peer_left", () => {
    closePeer();
    setStatus("The other person left. Waiting for them to come back…", "info");
  });
  socket.on("replaced", () => {
    stopAll();
    setStatus("This session was opened in another tab, so this tab was disconnected.", "error");
  });
  socket.on("disconnect", () => {
    if (joined) setStatus("Disconnected from the server. Trying to reconnect…", "info");
  });
  socket.on("error_msg", (e) => {
    if (!joined) setStatus(e.error, "error");
    else addChat({ error: e.error });
  });
  socket.on("chat", (m) => addChat(m));

  // ---------- chat ----------
  function addChat(m) {
    const empty = $("roomChatEmpty");
    if (empty) empty.remove();
    let box;
    if (m.error) {
      box = el("div", "msg msg-error", m.error);
    } else {
      box = el("div", "msg " + (m.role === myRole ? "msg-user" : "msg-ai"));
      box.appendChild(el("span", "meta", m.name + " · " + m.at));
      box.appendChild(el("div", null, m.text));
    }
    $("roomChat").appendChild(box);
    $("roomChat").scrollTop = $("roomChat").scrollHeight;
  }
  function sendChat() {
    const text = $("roomInput").value.trim();
    if (!text) return;
    socket.emit("chat", { text });
    $("roomInput").value = "";
  }
  $("roomSend").addEventListener("click", sendChat);
  $("roomInput").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); sendChat(); } });

  // ---------- controls ----------
  function toggle(button, track, onLabel, offLabel) {
    if (!track) return;
    track.enabled = !track.enabled;
    button.textContent = track.enabled ? onLabel : offLabel;
    button.setAttribute("aria-pressed", String(!track.enabled));
  }
  $("btnMic").addEventListener("click", () => toggle($("btnMic"), micTrack, "Mute microphone", "Unmute microphone"));
  $("btnCam").addEventListener("click", () => toggle($("btnCam"), camTrack, "Turn camera off", "Turn camera on"));

  async function stopScreen() {
    if (!screenTrack) return;
    screenTrack.onended = null;
    screenTrack.stop();
    screenTrack = null;
    $("btnScreen").textContent = "Share screen";
    $("btnScreen").setAttribute("aria-pressed", "false");
    showLocal(camTrack);
    await attachLocal();
  }
  $("btnScreen").addEventListener("click", async () => {
    if (screenTrack) { await stopScreen(); return; }
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      screenTrack = stream.getVideoTracks()[0];
      screenTrack.onended = stopScreen;                 // the browser's own "Stop sharing" button
      showLocal(screenTrack);
      await attachLocal();
      $("btnScreen").textContent = "Stop sharing";
      $("btnScreen").setAttribute("aria-pressed", "true");
    } catch (err) {
      setStatus("Screen sharing was cancelled or is not available in this browser.", "info");
    }
  });

  function stopAll() {
    [camTrack, micTrack, screenTrack].forEach((t) => { if (t) t.stop(); });
    closePeer();
    socket.disconnect();
  }
  $("btnEnd").addEventListener("click", () => {
    if (!window.confirm("Leave this session? You can come back while the room is open.")) return;
    stopAll();
    window.location.href = backUrl;
  });
  window.addEventListener("pagehide", () => { [camTrack, micTrack, screenTrack].forEach((t) => { if (t) t.stop(); }); });

  const mediaReady = startMedia();
});