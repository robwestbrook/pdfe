import * as pdfjsLib from "/static/vendor/pdfjs/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "/static/vendor/pdfjs/pdf.worker.min.mjs";

const state = { fileId: null, revision: 0, page: 0, pageCount: 0, pdf: null };
const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

function showError(error) {
  const box = $("#error");
  box.textContent = error.message;
  box.hidden = false;
}

function clearError() {
  $("#error").hidden = true;
}

function fileUrl(suffix = "") {
  return `/api/files/${state.fileId}${suffix}`;
}

async function run(action) {
  clearError();
  try {
    await action();
  } catch (error) {
    showError(error);
  }
}

async function openFile(fileId) {
  state.fileId = fileId;
  const info = await api(fileUrl());
  state.revision = info.revision;
  $("#file-name").textContent = info.name;
  $("#download").href = fileUrl("/download");
  $("#download").hidden = false;
  state.page = 0;
  await reload();
}

async function reload() {
  const bytes = await (await fetch(fileUrl("/download"))).arrayBuffer();
  state.pdf = await pdfjsLib.getDocument({ data: bytes }).promise;
  state.pageCount = state.pdf.numPages;
  if (state.page >= state.pageCount) state.page = 0;
  $("#revision").textContent = `revision ${state.revision}`;
  await renderStrip();
  await renderPage();
  await renderTools();
}

async function mutate(suffix, body) {
  const result = await api(fileUrl(suffix), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  state.revision = result.revision;
  await reload();
}

async function mutateForm(suffix, form) {
  const result = await api(fileUrl(suffix), { method: "POST", body: form });
  state.revision = result.revision;
  await reload();
}

async function renderStrip() {
  const strip = $("#page-strip");
  strip.replaceChildren();
  for (let i = 0; i < state.pageCount; i++) {
    const page = await state.pdf.getPage(i + 1);
    const viewport = page.getViewport({ scale: 0.18 });
    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;

    const thumb = document.createElement("div");
    thumb.className = `thumb${i === state.page ? " active" : ""}`;
    thumb.draggable = true;
    thumb.append(canvas, `${i + 1}`);
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
  await reload();
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
  const [blocks, images] = await Promise.all([
    api(`${pageUrl}/text`),
    api(`${pageUrl}/images`),
  ]);
  renderTextBlocks(blocks);
  renderImages(images);
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
      run(() =>
        mutate(`/pages/${state.page}/text/${block.id}`, {
          text: textarea.value,
          width: width.value === "" ? null : Number(width.value),
        }),
      ),
    );
    row.append(width, save);
    wrap.append(textarea, row);
    container.append(wrap);
  }
}

async function checkFont(font, text) {
  const params = new URLSearchParams({ font, text });
  const result = await api(`/api/fonts/check?${params}`);
  const banner = $("#font-banner");
  banner.textContent = result.fallback
    ? `Some text will use a substitute font (${result.fontname}), not the original.`
    : "";
  banner.hidden = !result.fallback;
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
    replace.accept = "image/png";
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

  $("#add-page").addEventListener("click", () => run(() => mutate("/pages", {})));

  $("#add-text-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.target;
    run(() =>
      mutate(`/pages/${state.page}/texts`, {
        text: form.text.value,
        x0: Number(form.x0.value),
        y0: Number(form.y0.value),
        x1: Number(form.x1.value),
        y1: Number(form.y1.value),
      }),
    );
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
