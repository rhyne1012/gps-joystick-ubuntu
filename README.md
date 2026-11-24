# GPS Joystick Ubuntu

Ubuntu Linux 上的 iPhone USB GPS 定位模擬搖桿工具，使用 Python（`pymobiledevice3` + FastAPI）與 Leaflet 深色互動地圖，透過 USB 免 `sudo` 同步模擬座標至 iOS 17+ / iOS 27 iPhone。

> 本專案為受 [gift-1215/GPSJoystick](https://github.com/gift-1215/GPSJoystick)（macOS Swift 原作）啟發而重新以 Python + Web UI 實作的 Ubuntu Linux Clean-room 版本，聚焦於 **USB 定位搖桿同步**（不包含原版的藍牙步數同步與 iOS HealthKit 配套 App）。

## 已實測驗證環境

- **主機系統**：Ubuntu 24.04.5 LTS（Python 3.12）
- **實測裝置**：iPhone 13（`iPhone14,5`），**iOS 27.2.1**
- **連線元件**：`pymobiledevice3 == 11.63.1` + `usbmuxd`
- **權限需求**：**免 `sudo`**（直接走 `pymobiledevice3` 內建 userspace RSD tunnel）

## 功能特色

- **深色互動地圖（Leaflet）**：支援點選起點、方向箭頭標記、即時移動軌跡線、跟隨位置、回到模擬位置、圖層切換（深色 / 標準 OSM / 衛星）。
- **虛擬搖桿與鍵盤操控**：滑鼠/觸控拖曳圓形搖桿或使用方向鍵 / `WASD`（支援斜向）；放開後保持當前航向持續移動，隨時可暫停／繼續。
- **速度控制**：0–120 km/h 滑桿與快速預設（步行 `5 km/h`、單車 `18 km/h`、開車 `50 km/h`）。
- **免費地點搜尋**：內建 Photon 自動完成 + Nominatim 備援搜尋（免 API Key），可預覽後設為新起點。
- **Ubuntu 初次連線輔助**：GUI 內建「偵測裝置」、「配對信任」、「顯示開發者模式（AMFI）」、「掛載 DDI」按鈕，不靠 Mac / Finder / Xcode 也能完成前置設定。
- **安全防呆**：中斷連線或關閉程式時會自動呼叫 `LocationSimulation.clear()` 恢復 iPhone 真實定位。

## 系統前置準備（Ubuntu）

1. 安裝並確認 `usbmuxd` 與 `uv`：
   ```bash
   sudo apt update
   sudo apt install -y usbmuxd libimobiledevice-utils
   ```
2. 如果尚未安裝 `uv`：
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. 用**支援資料傳輸的 USB 線**連接並解鎖 iPhone（若尚未信任電腦，可用介面中的「配對信任」或執行 `idevicepair pair`）。
4. 開啟 iPhone **設定 → 隱私權與安全性 → 開發者模式**並依提示重新啟動（若看不到選項，可使用下方 `probe_iphone.py reveal-dev-mode` 或介面裡的輔助按鈕叫出）。

## 安裝與啟動

```bash
git clone https://github.com/rhyne1012/gps-joystick-ubuntu.git
cd gps-joystick-ubuntu
uv sync
```

### 啟動 GPS 搖桿介面

```bash
# 預設開啟瀏覽器連到 http://127.0.0.1:8765
uv run gps-joystick-ubuntu

# 嘗試以 Chrome/Chromium 獨立桌面視窗模式開啟（--app）
uv run gps-joystick-ubuntu --app

# 僅啟動伺服器不自動開視窗
uv run gps-joystick-ubuntu --no-browser
```

### 命令列快速診斷與定位測試（`probe_iphone.py`）

若只想先驗證 USB、配對、開發者模式或單次測試座標：

```bash
# 檢查 USB 裝置、配對與開發者模式狀態
uv run python probe_iphone.py

# 觸發 USB 信任配對
uv run python probe_iphone.py pair

# 在 iPhone 設定中叫出「開發者模式」開關
uv run python probe_iphone.py reveal-dev-mode

# 測試送出台北 101 座標 (25.03396, 121.56447) 維持 2 秒後自動恢復真實定位
uv run python probe_iphone.py probe --test-location
```

## 常見問題排解

- **`lsusb` 完全看不到 Apple 裝置 (`05ac:*`)**
  1. 確認使用的是**可傳資料的 USB 線**，而非純充電線。
  2. 先**解鎖 iPhone** 再重新拔插。
  3. 嘗試插到主機上另一個直接連接主機板的 USB 孔（避開僅供電或供電不足的 Hub）。
- **測試結束後定位還停在模擬位置**
  - 重新接上同一台 iPhone，按介面中的「連接 iPhone」→「恢復定位」，或執行 `uv run python probe_iphone.py probe --test-location`（結束時會自動執行 `clear()`）。

## 授權與致謝

- 概念與互動設計參考自 [gift-1215/GPSJoystick](https://github.com/gift-1215/GPSJoystick)。
- 本專案採用個人開發測試用途之全新 Python / Web 實作。
