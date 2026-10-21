import * as pdfjsLib from "/static/vendor/pdfjs/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.mjs";

const state = { fileId: null, revision: 0, page: 0, pageCount: 0, pdf: null };
const $ = (selector) => document.querySelector(selector);

// Reloads run one after another, so an older render cannot overwrite a newer one.
let refreshChain = Promise.resolve();

// Every write carries a header that the server requires, so pages on other sites cannot make one.
async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = { ...(options.headers || {}) };
  if (method !== "GET") headers["X-Pdfe"] = "1";
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === "object" && detail ? detail.message : detail;
    const error = new Error(message || response.statusText);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

// An edit names the revision it was made from. If another window has changed the file since,
// the server refuses it and the editor reloads, so nothing is applied to the wrong content.
function editHeaders(extra = {}) {
  return { ...extra, "X-Base-Revision": String(state.revision) };
}

function showError(error) {
  const box = $("#error");
  box.textContent = error.message;
  box.hidden = false;
}

function clearError() {
  $("#error").hidden = true;
}

function showFontNotice(message) {
  const banner = $("#font-banner");
  banner.textContent = message;
  banner.hidden = !message;
}

async function run(action) {
  clearError();
  try {
    return await action();
  } catch (error) {
    if (error.status === 409) {
      showError(new Error("This file changed in another window. The editor has reloaded it; try the change again."));
      await refresh();
      return undefined;
    }
    showError(error);
    return undefined;
  }
}

function fileUrl(suffix = "") {
  return `/api/files/${state.fileId}${suffix}`;
}

function refresh() {
  const next = refreshChain.then(reload);
  refreshChain = next.catch(() => {});
  return next;
}

async function openFile(fileId) {
  state.fileId = fileId;
  const info = await api(fileUrl());
  state.revision = info.revision;
  $("#file-name").textContent = info.name;
  $("#download").href = fileUrl("/download");
  $("#download").setAttribute("download", info.name);
  $("#download").hidden = false;
  state.page = 0;
  await refresh();
}

async function reload() {
  const response = await fetch(fileUrl("/download"));
  // Revision numbers only grow. A reload that began before the latest edit may finish with an
  // older number, so keep the largest one seen.
  state.revision = Math.max(state.revision, Number(response.headers.get("X-Revision")));
  state.pdf = await pdfjsLib.getDocument({ data: await response.arrayBuffer() }).promise;
  state.pageCount = state.pdf.numPages;
  if (state.page >= state.pageCount) state.page = 0;
  renderStrip();
  await renderPage();
  await renderTools();
  await renderHistory();
  // The label changes last, so it never shows a revision whose panels are not drawn yet.
  $("#revision").textContent = `revision ${state.revision}`;
}

async function mutate(suffix, body) {
  const result = await api(fileUrl(suffix), {
    method: "POST",
    headers: editHeaders({ "content-type": "application/json" }),
    body: JSON.stringify(body),
  });
  state.revision = result.revision;
  await refresh();
  return result;
}

async function mutateForm(suffix, form) {
  const result = await api(fileUrl(suffix), { method: "POST", headers: editHeaders(), body: form });
  state.revision = result.revision;
  await refresh();
  return result;
}

async function revertTo(revision) {
  const result = await api(fileUrl("/revert"), {
    method: "POST",
    headers: editHeaders({ "content-type": "application/json" }),
    body: JSON.stringify({ revision }),
  });
  state.revision = result.revision;
  await refresh();
}

// Thumbnails come from the server, keyed by revision, so the browser keeps them and
// never redraws a page it already has.
function renderStrip() {
  const strip = $("#page-strip");
  strip.replaceChildren();
  for (let i = 0; i < state.pageCount; i++) {
    const image = document.createElement("img");
    image.alt = `Page ${i + 1}`;
    image.src = fileUrl(`/revisions/${state.revision}/pages/${i}/thumbnail`);

    const thumb = document.createElement("div");
    thumb.className = `thumb${i === state.page ? " active" : ""}`;
    thumb.draggable = true;
    thumb.append(image, `${i + 1}`);
    thumb.addEventListener("click", () => run(() => selectPage(i)));
    thumb.addEventListener("dragstart", (event) => event.dataTransfer.setData("text/plain", `${i}`));
    thumb.addEventListener("dragover", (event) => event.preventDefault());
    thumb.addEventListener("drop", (event) => {
      event.preventDefault();
      const from = Number(event.dataTransfer.getData("text/plain"));
      run(() => reorder(from, i));
    });
    strip.append(thumb);
  }
}

async function selectPage(index) {
  state.page = index;
  await refresh();
}

async function reorder(from, to) {
  if (from === to) return;
  const order = [...Array(state.pageCount).keys()];
  order.splice(to, 0, order.splice(from, 1)[0]);
  await mutate("/pages/reorder", { order });
}

async function renderPage() {
  const page = await state.pdf.getPage(state.page + 1);
  const viewport = page.getViewport({ scale: 1.2 });
  const canvas = $("#page-canvas");
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
}

async function renderTools() {
  const pageUrl = fileUrl(`/pages/${state.page}`);
  const [blocks, images] = await Promise.all([api(`${pageUrl}/text`), api(`${pageUrl}/images`)]);
  renderTextBlocks(blocks);
  renderImages(images);
}

async function renderHistory() {
  const info = await api(fileUrl("/revisions"));
  $("#undo").disabled = info.latest <= 1;
  const list = $("#history-list");
  list.replaceChildren();
  for (const number of [...info.revisions].reverse()) {
    const item = document.createElement("li");
    item.append(number === info.latest ? `Revision ${number} (current)` : `Revision ${number} `);
    if (number !== info.latest) {
      const restore = document.createElement("button");
      restore.textContent = "Restore";
      restore.addEventListener("click", () => run(() => revertTo(number)));
      item.append(restore);
    }
    list.append(item);
  }
}

function renderTextBlocks(blocks) {
  const container = $("#text-blocks");
  container.replaceChildren();
  if (blocks.length === 0) container.textContent = "No text on this page.";
  for (const block of blocks) {
    const wrap = document.createElement("div");
    wrap.className = "block";
    const textarea = document.createElement("textarea");
    textarea.value = block.text;
    textarea.addEventListener("input", () => run(() => checkFont(block.font, textarea.value)));
    const row = document.createElement("div");
    row.className = "row";
    const width = document.createElement("input");
    width.type = "number";
    width.placeholder = "width (pt), optional";
    const save = document.createElement("button");
    save.textContent = "Save";
    save.addEventListener("click", () =>
      run(async () => {
        const result = await mutate(`/pages/${state.page}/text/${block.id}`, {
          text: textarea.value,
          width: width.value === "" ? null : Number(width.value),
        });
        showFontNotice(result.fallback ? "Saved. Some text used a substitute font, not the original." : "");
      }),
    );
    row.append(width, save);
    wrap.append(textarea, row);
    container.append(wrap);
  }
}

async function checkFont(font, text) {
  const params = new URLSearchParams({ font, text });
  const result = await api(`/api/fonts/check?${params}`);
  showFontNotice(
    result.fallback ? `This text will use a substitute font (${result.fontname}), not the original.` : "",
  );
}

function renderImages(images) {
  const container = $("#image-list");
  container.replaceChildren();
  if (images.length === 0) container.textContent = "No images on this page.";
  for (const image of images) {
    const [x0, y0, x1, y1] = image.bbox.map((n) => Math.round(n));
    const wrap = document.createElement("div");
    wrap.className = "image-item";
    wrap.append(`Image ${image.xref} at (${x0}, ${y0}), ${x1 - x0} × ${y1 - y0}`);

    const move = inputRow(["dx", "dy"]);
    const moveButton = document.createElement("button");
    moveButton.textContent = "Move";
    moveButton.addEventListener("click", () =>
      run(() =>
        mutate(`/pages/${state.page}/images/${image.xref}`, {
          op: "move",
          dx: Number(move.inputs[0].value || 0),
          dy: Number(move.inputs[1].value || 0),
        }),
      ),
    );
    move.row.append(moveButton);

    const size = inputRow(["width", "height"]);
    const resizeButton = document.createElement("button");
    resizeButton.textContent = "Resize";
    resizeButton.addEventListener("click", () =>
      run(() =>
        mutate(`/pages/${state.page}/images/${image.xref}`, {
          op: "resize",
          width: Number(size.inputs[0].value),
          height: Number(size.inputs[1].value),
        }),
      ),
    );
    size.row.append(resizeButton);

    const actions = document.createElement("div");
    actions.className = "row";
    const remove = document.createElement("button");
    remove.textContent = "Delete";
    remove.addEventListener("click", () =>
      run(() => mutate(`/pages/${state.page}/images/${image.xref}`, { op: "delete" })),
    );
    const replace = document.createElement("input");
    replace.type = "file";
    replace.accept = "image/png,image/gif,image/jpeg,.wpg";
    replace.addEventListener("change", () => {
      const form = new FormData();
      form.append("file", replace.files[0]);
      run(() => mutateForm(`/pages/${state.page}/images/${image.xref}/replace`, form));
    });
    actions.append(remove, replace);

    wrap.append(move.row, size.row, actions);
    container.append(wrap);
  }
}

function inputRow(labels) {
  const row = document.createElement("div");
  row.className = "row";
  const inputs = labels.map((label) => {
    const input = document.createElement("input");
    input.type = "number";
    input.placeholder = label;
    row.append(input);
    return input;
  });
  return { row, inputs };
}

function wireControls() {
  $("#open-file").addEventListener("change", (event) =>
    run(async () => {
      const form = new FormData();
      form.append("file", event.target.files[0]);
      const result = await api("/api/files", { method: "POST", body: form });
      await openFile(result.id);
    }),
  );

  $("#new-doc").addEventListener("click", () =>
    run(async () => {
      const result = await api("/api/documents", { method: "POST" });
      await openFile(result.id);
    }),
  );

  $("#undo").addEventListener("click", () => run(() => revertTo(state.revision - 1)));

  $("#add-page").addEventListener("click", () => run(() => mutate("/pages", {})));

  $("#rotate-left").addEventListener("click", () =>
    run(() => mutate("/pages/rotate", { index: state.page, degrees: 270 })),
  );

  $("#rotate-right").addEventListener("click", () =>
    run(() => mutate("/pages/rotate", { index: state.page, degrees: 90 })),
  );

  $("#delete-page").addEventListener("click", () => {
    if (!confirm(`Delete page ${state.page + 1}? This creates a new revision; earlier ones are kept.`)) return;
    run(() => mutate("/pages/delete", { indexes: [state.page] }));
  });

  $("#add-text-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.target;
    run(async () => {
      const result = await mutate(`/pages/${state.page}/texts`, {
        text: form.text.value,
        x0: Number(form.x0.value),
        y0: Number(form.y0.value),
        x1: Number(form.x1.value),
        y1: Number(form.y1.value),
      });
      showFontNotice(result.fallback ? "Added. Some text used a substitute font, not the original." : "");
    });
  });

  $("#add-picture-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.target;
    const body = new FormData();
    body.append("file", form.file.files[0]);
    for (const name of ["x0", "y0", "x1", "y1"]) body.append(name, form[name].value);
    run(() => mutateForm(`/pages/${state.page}/pictures`, body));
  });
}

wireControls();
