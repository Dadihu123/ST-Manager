function hasNativeDownloads() {
  return typeof window.stmHost?.saveBase64FileAsync === 'function' ||
    typeof window.stmHost?.saveBase64File === 'function';
}

let downloadRequestId = 0;

export async function downloadFileFromApi({
  url,
  method = "POST",
  body,
  headers = {},
  defaultFilename = "download.json",
  showToast,
  successMessage,
}) {
  const response = await fetch(url, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const contentDisposition =
    response.headers.get("Content-Disposition") ||
    response.headers.get("content-disposition") ||
    "";
  const contentType = response.headers.get("content-type") || "";
  const isAttachment = contentDisposition.toLowerCase().includes("attachment");

  if (
    !response.ok ||
    (!isAttachment && contentType.includes("application/json"))
  ) {
    const payload = await response.json().catch(() => null);
    const message =
      payload?.msg || payload?.message || `下载失败 (${response.status})`;
    throw new Error(message);
  }

  const filenameMatch = contentDisposition.match(
    /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i,
  );
  const filename = decodeURIComponent(
    filenameMatch?.[1] || filenameMatch?.[2] || defaultFilename,
  );
  const blob = await response.blob();
  if (hasNativeDownloads()) {
    await saveBlobToHost(blob, filename);
    if (successMessage && typeof showToast === 'function') showToast(successMessage, 1800);
    return;
  }
  const blobUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(blobUrl);

  if (successMessage && typeof showToast === "function") {
    showToast(successMessage, 1800);
  }
}

export async function saveBlobToHost(blob, filename) {
  const data = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(reader.error || new Error('读取导出文件失败'));
    reader.readAsDataURL(blob);
  });
  const mime = blob.type || 'application/octet-stream';
  if (typeof window.stmHost?.saveBase64FileAsync === 'function') {
    const id = `download-${Date.now()}-${++downloadRequestId}`;
    await new Promise((resolve, reject) => {
      const onResult = event => {
        if (event.detail?.id !== id) return;
        window.removeEventListener('host:download-result', onResult);
        if (event.detail.success) resolve();
        else reject(new Error(event.detail.message || '保存导出文件失败'));
      };
      window.addEventListener('host:download-result', onResult);
      try {
        window.stmHost.saveBase64FileAsync(id, data, filename, mime);
      } catch (error) {
        window.removeEventListener('host:download-result', onResult);
        reject(error);
      }
    });
  } else if (!window.stmHost.saveBase64File(data, filename, mime)) {
    throw new Error('保存导出文件失败');
  }
}

// 捕获已有 <a download> 的 blob 导出，在业务代码 revoke URL 前取得 Blob。
export function installNativeDownloads() {
  if (!hasNativeDownloads()) return;
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[download]');
    if (!link || !/^(blob:|data:)/.test(link.href)) return;
    event.preventDefault();
    const filename = link.download || 'stm-export';
    // fetch 同步取得 blob URL 的引用；后续 revoke 不影响已发起的读取。
    fetch(link.href).then(response => response.blob())
      .then(blob => saveBlobToHost(blob, filename))
      .catch(error => { console.error(error); window.alert('导出失败：' + error.message); });
  }, true);
}
