// Shrinks a chosen photo in the browser before upload (the server has a small size limit and
// re-checks everything anyway). Transparent areas are filled with white. No HTML-string insertion.
document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("photoInput");
  const note = document.getElementById("photoNote");
  if (!input || !note) return;
  const MAX_SIDE = 600;

  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) { note.textContent = ""; return; }
    if (!file.type.startsWith("image/")) {
      note.textContent = "Please choose an image file.";
      return;
    }
    try {
      const bitmap = await createImageBitmap(file);
      const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
      if (!blob) throw new Error("no image data");
      const transfer = new DataTransfer();
      transfer.items.add(new File([blob], "photo.jpg", { type: "image/jpeg" }));
      input.files = transfer.files;
      note.textContent = "Photo prepared (" + Math.round(blob.size / 1024) +
        " KB). It will be cropped to a square.";
    } catch (err) {
      note.textContent = "Could not prepare the photo here. If it is larger than 700 KB, choose a smaller image.";
    }
  });
});