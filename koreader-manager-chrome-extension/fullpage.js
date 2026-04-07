// ============================================
// TAB SWITCHING LOGIC
// ============================================
document.querySelectorAll('.tab-button').forEach(button => {
  button.addEventListener('click', () => {
    document
      .querySelectorAll('.tab-button')
      .forEach(btn => btn.classList.remove('active'));
    document
      .querySelectorAll('.tab-content')
      .forEach(content => content.classList.remove('active'));

    button.classList.add('active');
    const tabName = button.dataset.tab;
    document.getElementById(`${tabName}-tab`).classList.add('active');
  });
});

// ============================================
// BOOKMARK EXPORTER LOGIC
// ============================================
let allBookmarks = [];
let selectedUrls = new Set();

chrome.bookmarks.getTree(bookmarkTree => {
  renderBookmarkTree(bookmarkTree);
});

function renderBookmarkTree(bookmarkNodes) {
  const container = document.getElementById('bookmarkTree');
  container.innerHTML = '';

  bookmarkNodes.forEach(node => {
    traverseBookmarks(node, container, 0);
  });

  updateExportButton();
}

function traverseBookmarks(node, container, level) {
  if (node.title === '' && level === 0) {
    if (node.children) {
      node.children.forEach(child =>
        traverseBookmarks(child, container, level),
      );
    }
    return;
  }

  const div = document.createElement('div');
  div.className = `bookmark-item indent-${Math.min(level, 4)}`;

  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.id = `bookmark-${node.id}`;
  checkbox.dataset.nodeId = node.id;

  const label = document.createElement('label');
  label.htmlFor = checkbox.id;

  if (node.children) {
    label.textContent = `📁 ${node.title}`;
    label.className = 'folder';

    checkbox.addEventListener('change', e => {
      toggleFolder(node, e.target.checked);
      updateExportButton();
    });
  } else {
    label.textContent = node.title || node.url;
    label.className = 'url';

    allBookmarks.push({ id: node.id, url: node.url, title: node.title });

    checkbox.addEventListener('change', e => {
      if (e.target.checked) {
        selectedUrls.add(node.url);
      } else {
        selectedUrls.delete(node.url);
      }
      updateExportButton();
    });
  }

  div.appendChild(checkbox);
  div.appendChild(label);
  container.appendChild(div);

  if (node.children) {
    node.children.forEach(child =>
      traverseBookmarks(child, container, level + 1),
    );
  }
}

function toggleFolder(folderNode, checked) {
  function processNode(node) {
    if (node.children) {
      node.children.forEach(child => processNode(child));
    } else {
      const checkbox = document.querySelector(
        `input[data-node-id="${node.id}"]`,
      );
      if (checkbox) {
        checkbox.checked = checked;
        if (checked) {
          selectedUrls.add(node.url);
        } else {
          selectedUrls.delete(node.url);
        }
      }
    }
  }

  processNode(folderNode);
}

function updateExportButton() {
  const btn = document.getElementById('exportBtn');
  btn.textContent = `Export Selected (${selectedUrls.size})`;
  btn.disabled = selectedUrls.size === 0;
}

function showBookmarkStatus(message, type = 'success') {
  const status = document.getElementById('bookmarkStatus');
  status.className = `status show ${type}`;
  status.textContent = message;

  setTimeout(() => {
    status.className = 'status';
  }, 5000);
}

function showNotification(urlCount) {
  const message =
    urlCount === 1
      ? "URL saved! Please run the 'Article to Ebook Converter' program to convert saved URLs into .epub files."
      : `${urlCount} URLs saved! Please run the 'Article to Ebook Converter' program to convert saved URLs into .epub files.`;

  chrome.notifications.create({
    type: 'basic',
    iconUrl: 'icon.png',
    title: 'Bookmark Exporter',
    message: message,
    priority: 2,
  });
}

document.getElementById('exportBtn').addEventListener('click', () => {
  if (selectedUrls.size === 0) return;

  const csvContent = Array.from(selectedUrls).join(',');
  const blob = new Blob([csvContent], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);

  chrome.downloads.download(
    {
      url: url,
      filename: 'urls.csv',
      saveAs: false,
    },
    downloadId => {
      URL.revokeObjectURL(url);
      showBookmarkStatus(`✓ Exported ${selectedUrls.size} URLs to urls.csv`);
      showNotification(selectedUrls.size);
    },
  );
});

document.getElementById('selectAllBtn').addEventListener('click', () => {
  document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.checked = true;
  });

  allBookmarks.forEach(bookmark => {
    selectedUrls.add(bookmark.url);
  });

  updateExportButton();
});

document.getElementById('deselectAllBtn').addEventListener('click', () => {
  document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.checked = false;
  });

  selectedUrls.clear();
  updateExportButton();
});

// ============================================
// KOREADER FINDER LOGIC
// ============================================
const KINDLE_FILE_PATH = '/files/mnt/us/koreader/HOME/';

const koreaderStatusEl = document.getElementById('koreaderStatus');
const scanBtn = document.getElementById('scanBtn');
const manualBtn = document.getElementById('manualBtn');
const networkPrefixInput = document.getElementById('networkPrefix');
const savedIpSection = document.getElementById('savedIpSection');
const savedIpValue = document.getElementById('savedIpValue');
const openSavedBtn = document.getElementById('openSavedBtn');
const forgetIpBtn = document.getElementById('forgetIpBtn');
const scanProgress = document.getElementById('scanProgress');
const scanProgressText = document.getElementById('scanProgressText');
const progressFill = document.getElementById('progressFill');

loadSavedIp();

function showKOReaderStatus(message, type = 'success') {
  koreaderStatusEl.textContent = message;
  koreaderStatusEl.className = `status show ${type}`;
}

function hideKOReaderStatus() {
  koreaderStatusEl.className = 'status';
}

async function saveKindleIp(ip) {
  await chrome.storage.local.set({ kindleIp: ip });
  displaySavedIp(ip);
}

async function loadSavedIp() {
  const result = await chrome.storage.local.get('kindleIp');
  if (result.kindleIp) {
    displaySavedIp(result.kindleIp);
  }
}

function displaySavedIp(ip) {
  savedIpValue.textContent = ip;
  savedIpSection.style.display = 'block';
}

function openKindleFiles(ip) {
  chrome.tabs.create({
    url: `http://${ip}${KINDLE_FILE_PATH}`,
  });
}

async function checkKindleIp(ip) {
  return new Promise(resolve => {
    chrome.runtime.sendMessage({ action: 'checkIp', ip: ip }, response => {
      resolve(response.isKindle);
    });
  });
}

async function scanNetwork() {
  scanBtn.disabled = true;
  manualBtn.disabled = true;
  hideKOReaderStatus();
  scanProgress.style.display = 'block';
  progressFill.style.width = '0%';

  let prefix = networkPrefixInput.value.trim();

  if (!prefix) {
    scanProgressText.textContent = '🔍 Detecting network...';
    prefix = await detectNetworkPrefix();
    networkPrefixInput.value = prefix;
  }

  scanProgressText.textContent = `🔍 Scanning ${prefix}.x network...`;

  // Router/gateway IPs to skip
  const skipIps = [1, 254, 255];

  // Check common device IPs first for faster results
  const priorityIps = [
    100, 101, 102, 103, 150, 151, 171, 172, 200, 201, 50, 51, 52, 10, 11, 12,
    20, 21, 30,
  ];

  let found = false;
  let checkedCount = 0;
  const totalToCheck = 253 - skipIps.length;

  // Check priority IPs first
  for (const lastOctet of priorityIps) {
    if (skipIps.includes(lastOctet)) continue;

    const ip = `${prefix}.${lastOctet}`;
    checkedCount++;
    const progress = Math.round((checkedCount / totalToCheck) * 100);
    progressFill.style.width = `${progress}%`;
    scanProgressText.textContent = `Checking ${ip}... (${progress}%)`;

    const isKindle = await checkKindleIp(ip);

    if (isKindle) {
      scanProgress.style.display = 'none';
      showKOReaderStatus(`✅ Kindle found at ${ip}!`, 'success');
      await saveKindleIp(ip);

      setTimeout(() => {
        openKindleFiles(ip);
      }, 500);

      found = true;
      break;
    }
  }

  // Full scan if not found in priority IPs
  if (!found) {
    for (let i = 2; i <= 253; i++) {
      if (skipIps.includes(i) || priorityIps.includes(i)) continue;

      const ip = `${prefix}.${i}`;
      checkedCount++;
      const progress = Math.round((checkedCount / totalToCheck) * 100);
      progressFill.style.width = `${progress}%`;
      scanProgressText.textContent = `Checking ${ip}... (${progress}%)`;

      const isKindle = await checkKindleIp(ip);

      if (isKindle) {
        scanProgress.style.display = 'none';
        showKOReaderStatus(`✅ Kindle found at ${ip}!`, 'success');
        await saveKindleIp(ip);

        setTimeout(() => {
          openKindleFiles(ip);
        }, 500);

        found = true;
        break;
      }
    }
  }

  scanProgress.style.display = 'none';

  if (!found) {
    showKOReaderStatus(
      '❌ Kindle not found on this network. Try manual IP or check if File Browser is running.',
      'error',
    );
  }

  scanBtn.disabled = false;
  manualBtn.disabled = false;
}

async function detectNetworkPrefix() {
  const commonNetworks = [
    '192.168.1',
    '192.168.0',
    '192.168.2',
    '10.0.0',
    '10.0.1',
    '172.16.0',
  ];

  for (const network of commonNetworks) {
    const ip = `${network}.100`;
    const isReachable = await checkKindleIp(ip);
    if (isReachable) {
      return network;
    }
  }

  return '192.168.1';
}

function manualIpEntry() {
  const ip = prompt('Enter Kindle IP address (e.g., 192.168.1.171):');

  if (ip) {
    hideKOReaderStatus();
    scanProgress.style.display = 'block';
    progressFill.style.width = '50%';
    scanProgressText.textContent = `🔍 Checking ${ip}...`;

    checkKindleIp(ip).then(async isKindle => {
      scanProgress.style.display = 'none';

      if (isKindle) {
        showKOReaderStatus(`✅ Connected to ${ip}!`, 'success');
        await saveKindleIp(ip);

        setTimeout(() => {
          openKindleFiles(ip);
        }, 500);
      } else {
        showKOReaderStatus(
          `❌ Could not connect to ${ip}. Check IP and File Browser.`,
          'error',
        );
      }
    });
  }
}

async function forgetSavedIp() {
  await chrome.storage.local.remove('kindleIp');
  savedIpSection.style.display = 'none';
  hideKOReaderStatus();
}

scanBtn.addEventListener('click', scanNetwork);
manualBtn.addEventListener('click', manualIpEntry);
openSavedBtn.addEventListener('click', async () => {
  const result = await chrome.storage.local.get('kindleIp');
  if (result.kindleIp) {
    openKindleFiles(result.kindleIp);
  }
});
forgetIpBtn.addEventListener('click', forgetSavedIp);
