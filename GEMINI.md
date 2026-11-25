# Apex Mini Rally (Tiny Track Rally Custom) - Project Memory & Engineering Notes

## 1. Android / LDPlayer 3D Harita Yüklenmeme ve Görüntü Donması Sorunu (Çözüldü - v1.2.5)

### Belirti (Symptom)
- Oyun PC'de (Windows Vulkan / Forward+ veya GL Compatibility) kusursuz çalışırken, Android emülatörde (LDPlayer / AOSP `emugl`) açıldığında **2D arayüz (UI, butonlar, yazılar, HUD)** normal çalışıyor ancak **3D harita, yol ve araçlar hiç yüklenmiyordu**.
- Arka plan tamamen gökyüzü mavisi (`#9ec7fa`) kalıyor ve yalnızca ekranın sağ üst çeyreğinde (`x=640..1280, y=0..448`) ilk kareden kalma tek bir çam ağacı (`decoration-forest`) tamamen donmuş şekilde duruyordu. Menüden yarışa girilse bile 3D görüntüdeki pikseller hiç değişmiyordu (`max pixel diff = 0`).

### Kök Neden (Root Cause)
1. **Godot 4.6 GLES3 (`gl_compatibility`) UBO Güncelleme Akışı:**
   Godot 4.6'nın OpenGL ES 3.0 sürücüsü (`RasterizerSceneGLES3`), her karede kamera matrisi (`SceneData`), 3D obje/araç konumları (`InstanceData`) ve ışık verilerini (`DirectionalLights`, `OmniLights`, `SpotLights`) GPU'ya göndermek için **Uniform Buffer Object (UBO)** kullanır ve şu OpenGL çağrılarını sırayla yapar:
   - `glBindBufferBase(GL_UNIFORM_BUFFER, index, buffer_id)`
   - `glBufferData(GL_UNIFORM_BUFFER, size, data, GL_STREAM_DRAW)` veya `glBufferSubData(GL_UNIFORM_BUFFER, ...)`
   - İşlem bitince genel hedefi temizlemek için: `glBindBuffer(GL_UNIFORM_BUFFER, 0)`

2. **LDPlayer / Android Emülatör OpenGL ES Encoder (`libstagefright_gl2enc.so` & `libOpenglCodecCommon.so`) Hatası:**
   - OpenGL ES 3.0 spesifikasyonuna göre `glBindBufferBase(GL_UNIFORM_BUFFER, index, buffer)` çağrısı **hem** indeksli UBO slotunu (`index`) **hem de** genel `GL_UNIFORM_BUFFER` hedefini (`generic binding point`) aynı anda bağlamak zorundadır.
   - Ancak LDPlayer'ın `GL2Encoder::s_glBindBufferBase` fonksiyonu içerisindeki `GLClientState::isIndexedBindNoOp(target, index, buffer)` kontrolü yalnızca *"Bu `buffer` zaten bu `index` slotuna bağlı mı?"* diye bakar; genel `GL_UNIFORM_BUFFER` bağının `glBindBuffer(GL_UNIFORM_BUFFER, 0)` ile sıfırlanmış olduğunu **kontrol etmez**.
   - **Sonuç:**
     - **Kare 1 (Frame 1):** UBO'lar ilk kez bağlandığı için `isIndexedBindNoOp` `false` döner ve ilk kare (kamera henüz `(0,0,0)` noktasındayken gördüğü tek bir ağaç) çizilir. Kare sonunda Godot `glBindBuffer(GL_UNIFORM_BUFFER, 0)` çağırarak genel bağı `0` yapar.
     - **Kare 2 ve Sonrası (Frame 2+):** Godot aynı UBO'yu tekrar `glBindBufferBase` ile bağladığında LDPlayer bunu "gereksiz işlem (no-op)" sanıp erken çıkar ve genel `GL_UNIFORM_BUFFER` bağını `0`'da bırakır. Hemen ardından gelen tüm `glBufferData` / `glBufferSubData` çağrıları:
       `E emuglGLESv2_enc: GL2Encoder.cpp:s_glBufferData:975 GL error 0x502 condition [bufferId==0]`
       hatasıyla reddedilir. Kamera, harita ve araçların yeni koordinatları GPU'ya hiç ulaşamaz.

### Kalıcı Çözüm (Fix)
- [`scripts/patch_android_gles3_ubo.py`](scripts/patch_android_gles3_ubo.py) betiği yazıldı.
- Bu betik, Android derlemesi içindeki `arm64-v8a/libgodot_android.so` ikili (binary) dosyasını yamayarak içerisindeki **34 adet `bl glBindBufferBase`** ve **3 adet `bl glBindBufferRange`** çağrısını `UPNP_UpdatePinhole` alanına yerleştirilen ARM64 trampoline fonksiyonlarına yönlendirir.
- Trampoline fonksiyonu önce orijinal `glBindBufferBase` / `glBindBufferRange` çağrısını yapar, hemen ardından `glBindBuffer(target, buffer)` çağırarak genel `GL_UNIFORM_BUFFER` bağının her zaman güncel kalmasını garanti eder.
- [`.github/workflows/android.yml`](.github/workflows/android.yml) CI/CD hattına Gradle paketlemesinden hemen önce `python3 scripts/patch_android_gles3_ubo.py android/build/libs` adımı eklendi.

---

## 2. PC ve Mobil Debug Komutları
- **PC Debug Konsolu Başlatıcı:** `D:\temp\godot\run_game.bat` ve `C:\Users\erens\Desktop\OYNA_APEX_RALLY_DEBUG.bat`
- **LDPlayer OpenGL Hata Kontrolü:**
  ```powershell
  adb -s emulator-5556 logcat -d | Select-String "s_glBufferData"
  ```
  Yamalı APK'da bu çıktı **0 hata** döndürmelidir.
