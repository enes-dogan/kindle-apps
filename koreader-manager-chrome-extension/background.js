// Background service worker for checking Kindle IPs
const CHECK_TIMEOUT = 100; // Increased timeout for better reliability

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'checkIp') {
    checkIfKindle(request.ip).then(isKindle => {
      sendResponse({ isKindle: isKindle });
    });
    return true; // Keep the message channel open for async response
  }
});

async function checkIfKindle(ip) {
  const url = `http://${ip}/files/mnt/us/koreader/HOME/`;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), CHECK_TIMEOUT);

    // Try to fetch the KOReader file browser endpoint
    const response = await fetch(url, {
      method: 'HEAD',
      signal: controller.signal,
      mode: 'no-cors', // This allows the request but we can't read the response
    });

    clearTimeout(timeoutId);

    // With no-cors, we can't check status, but if it doesn't throw, it reached something
    return true;
  } catch (error) {
    // If fetch fails (network error, timeout, CORS, etc.), try ping-like approach
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), CHECK_TIMEOUT);

      // Try a simpler endpoint that might respond
      const pingResponse = await fetch(`http://${ip}:80`, {
        method: 'HEAD',
        signal: controller.signal,
        mode: 'no-cors',
      });

      clearTimeout(timeoutId);

      // If we got here, something is listening on port 80
      // Now verify it's actually KOReader by trying the specific path
      const verifyController = new AbortController();
      const verifyTimeoutId = setTimeout(
        () => verifyController.abort(),
        CHECK_TIMEOUT,
      );

      await fetch(url, {
        method: 'GET',
        signal: verifyController.signal,
        mode: 'no-cors',
      });

      clearTimeout(verifyTimeoutId);
      return true;
    } catch (pingError) {
      // Neither method worked - this IP is not reachable or not a Kindle
      return false;
    }
  }
}
