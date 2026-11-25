package com.localcontrol

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import com.google.zxing.integration.android.IntentIntegrator
import org.json.JSONObject

class MainActivity : Activity(), RemoteView.Listener {

    private data class Preset(val label: String, val width: Int, val quality: Int, val fps: Int)

    private val presets = listOf(
        Preset("Baixa", 960, 55, 24),
        Preset("Média", 1280, 65, 30),
        Preset("Alta", 1600, 72, 30),
        Preset("Máxima", 1920, 80, 30)
    )

    private lateinit var prefs: SharedPreferences

    private lateinit var connectRoot: View
    private lateinit var remoteRoot: View
    private lateinit var hostInput: EditText
    private lateinit var portInput: EditText
    private lateinit var pinInput: EditText
    private lateinit var connectBtn: TextView
    private lateinit var scanBtn: TextView
    private lateinit var pairBtn: TextView
    private lateinit var forgetBtn: TextView
    private lateinit var connectStatus: TextView
    private lateinit var profileHomeBtn: TextView
    private lateinit var profileAwayBtn: TextView

    private lateinit var remoteView: RemoteView
    private lateinit var topBar: View
    private lateinit var bottomBar: View
    private lateinit var showBtn: TextView
    private lateinit var statusText: TextView
    private lateinit var monitorBtn: TextView
    private lateinit var closeBtn: TextView
    private lateinit var modeBtn: TextView
    private lateinit var kbBtn: TextView
    private lateinit var keysBtn: TextView
    private lateinit var qualityBtn: TextView
    private lateinit var hideBtn: TextView
    private lateinit var keysPanel: View
    private lateinit var keysRow: LinearLayout
    private lateinit var kbInput: EditText

    private var client: RemoteClient? = null
    private var presetIndex = 1
    private var connected = false
    private var connecting = false
    private var scanning = false
    private var keyboardVisible = false
    private var monitorIndex = 1
    private var monitorCount = 1
    private var latencyMs = 0
    private var fpsNow = 0
    private var deviceName = ""
    private var pendingPair: Pairing.Info? = null
    private val REQ_CAMERA = 1001

    private val sticky = LinkedHashSet<String>()
    private val modButtons = HashMap<String, TextView>()
    private var lastTyped = ""
    private var syncingText = false

    /** 0 = Casa (Wi-Fi local), 1 = Fora (Tailscale/outra rede). */
    private var profile = 0
    private val profileKeys = arrayOf("casa", "fora")

    private val ui = Handler(Looper.getMainLooper())

    // ------------------------------------------------------------ ciclo de vida

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        hideSystemBars()

        prefs = getSharedPreferences("localcontrol", MODE_PRIVATE)

        bindViews()

        // Migra o endereco unico antigo para o perfil "Casa" (so na primeira vez).
        if (!prefs.contains("host_casa")) {
            prefs.edit()
                .putString("host_casa", prefs.getString("host", ""))
                .putString("port_casa", prefs.getString("port", "8765"))
                .apply()
        }
        profile = prefs.getInt("perfil", 0).coerceIn(0, 1)
        hostInput.setText(prefs.getString("host_" + profileKeys[profile], ""))
        portInput.setText(prefs.getString("port_" + profileKeys[profile], "8765"))
        pinInput.setText(prefs.getString("pin", ""))
        updateProfileButtons()
        presetIndex = prefs.getInt("preset", 1).coerceIn(0, presets.size - 1)
        qualityBtn.text = "Q: ${presets[presetIndex].label}"

        remoteView.listener = this
        remoteView.mode = prefs.getInt("mode", RemoteView.MODE_ABS)
        updateModeLabel()

        connectBtn.setOnClickListener { doConnect() }
        scanBtn.setOnClickListener { scanNetwork() }
        pairBtn.setOnClickListener { startQrScan() }
        forgetBtn.setOnClickListener { forgetPc() }
        profileHomeBtn.setOnClickListener { switchProfile(0) }
        profileAwayBtn.setOnClickListener { switchProfile(1) }
        closeBtn.setOnClickListener { disconnect() }
        modeBtn.setOnClickListener { toggleMode() }
        kbBtn.setOnClickListener { toggleKeyboard() }
        keysBtn.setOnClickListener { toggleKeysPanel() }
        qualityBtn.setOnClickListener { cycleQuality() }
        hideBtn.setOnClickListener { setBarsVisible(false) }
        showBtn.setOnClickListener { setBarsVisible(true) }
        monitorBtn.setOnClickListener { cycleMonitor() }

        setupKeyboard()
        buildKeys()
        // Um link recebido enquanto o app estava fechado so deve ser tratado na
        // criacao inicial, nao de novo depois de recriar a activity.
        if (savedInstanceState == null) handleIntent(intent)
    }

    private fun bindViews() {
        connectRoot = findViewById(R.id.connectRoot)
        remoteRoot = findViewById(R.id.remoteRoot)
        hostInput = findViewById(R.id.hostInput)
        portInput = findViewById(R.id.portInput)
        pinInput = findViewById(R.id.pinInput)
        connectBtn = findViewById(R.id.connectBtn)
        scanBtn = findViewById(R.id.scanBtn)
        pairBtn = findViewById(R.id.pairBtn)
        forgetBtn = findViewById(R.id.forgetBtn)
        connectStatus = findViewById(R.id.connectStatus)
        profileHomeBtn = findViewById(R.id.profileHomeBtn)
        profileAwayBtn = findViewById(R.id.profileAwayBtn)

        remoteView = findViewById(R.id.remoteView)
        topBar = findViewById(R.id.topBar)
        bottomBar = findViewById(R.id.bottomBar)
        showBtn = findViewById(R.id.showBtn)
        statusText = findViewById(R.id.statusText)
        monitorBtn = findViewById(R.id.monitorBtn)
        closeBtn = findViewById(R.id.closeBtn)
        modeBtn = findViewById(R.id.modeBtn)
        kbBtn = findViewById(R.id.kbBtn)
        keysBtn = findViewById(R.id.keysBtn)
        qualityBtn = findViewById(R.id.qualityBtn)
        hideBtn = findViewById(R.id.hideBtn)
        keysPanel = findViewById(R.id.keysPanel)
        keysRow = findViewById(R.id.keysRow)
        kbInput = findViewById(R.id.kbInput)
    }

    override fun onDestroy() {
        client?.stop()
        client = null
        super.onDestroy()
    }

    override fun onPause() {
        saveProfile()
        super.onPause()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    // ------------------------------------------------------------ pareamento por QR

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        if (intent?.action != Intent.ACTION_VIEW) return
        val raw = intent.data?.toString() ?: return
        val info = Pairing.parse(raw)
        if (info == null) {
            toast("QR inválido ou incompleto")
            showPairHelp(raw)
            return
        }
        // Um link pode vir de qualquer app/navegador, não só da câmera. Confirme
        // antes de conectar: o QR lido dentro do app continua automático.
        AlertDialog.Builder(this)
            .setTitle("Abrir link de pareamento?")
            .setMessage(
                "PC: ${info.name.ifEmpty { info.host }} (${info.host}:${info.port})\n\n" +
                    "Chave: " + LocalCrypto.formatFingerprint(info.fingerprint) + "\n\n" +
                    "Só continue se este link foi exibido no PC que você quer controlar."
            )
            .setPositiveButton("Parear") { _, _ -> handlePairUri(raw) }
            .setNegativeButton("Cancelar", null)
            .setCancelable(false)
            .show()
    }

    private fun startQrScan() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
            checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), REQ_CAMERA)
            return
        }
        launchScanner()
    }

    private fun launchScanner() {
        try {
            IntentIntegrator(this)
                .setDesiredBarcodeFormats(IntentIntegrator.QR_CODE)
                .setPrompt("Aponte para o QR exibido no PC")
                .setBeepEnabled(false)
                .setOrientationLocked(false)
                .initiateScan()
        } catch (_: Exception) {
            showPairHelp(null)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_CAMERA) return
        if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            launchScanner()
        } else {
            toast("Sem permissão de câmera: cole o link do QR")
            showPairHelp(null)
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        val result = IntentIntegrator.parseActivityResult(requestCode, resultCode, data)
        if (result != null) {
            val contents = result.contents
            if (contents.isNullOrBlank()) {
                toast("Leitura cancelada")
            } else {
                handlePairUri(contents)
            }
            return
        }
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
    }

    private fun handlePairUri(raw: String) {
        val info = Pairing.parse(raw)
        if (info == null) {
            toast("QR inválido ou incompleto")
            showPairHelp(raw)
            return
        }
        if (client != null || connecting) {
            toast("Desconecte antes de parear outro PC")
            return
        }

        // QR com IP 100.x e' Tailscale; o resto e' a rede local.
        val novo = if (info.host.startsWith("100.")) 1 else 0
        if (novo != profile) {
            saveProfile()
            profile = novo
            prefs.edit().putInt("perfil", novo).apply()
            updateProfileButtons()
        }

        hostInput.setText(info.host)
        portInput.setText(info.port.toString())
        pinInput.setText("")
        saveProfile()
        pendingPair = info
        connectStatus.text = "QR lido: pareando com ${info.name.ifEmpty { info.host }}…"
        doPairing(info)
    }

    private fun doPairing(info: Pairing.Info) {
        if (client != null || connecting) return
        connecting = true
        connectBtn.isEnabled = false
        pairBtn.isEnabled = false
        startClient(
            host = info.host,
            port = info.port,
            pin = null,
            preset = presets[presetIndex],
            fingerprint = info.fingerprint,
            pairToken = info.token
        )
    }

    private fun forgetPc() {
        AlertDialog.Builder(this)
            .setTitle("Esquecer este PC")
            .setMessage(
                "Apaga deste aparelho a chave do PC e o PIN salvo.\n\n" +
                    "Para conectar de novo, leia um novo QR no PC (ou digite o PIN). " +
                    "No PC, use \"Esquecer aparelhos\" para revogar também do outro lado."
            )
            .setPositiveButton("Esquecer") { _, _ ->
                prefs.edit()
                    .remove(spkiKey())
                    .remove(deviceKey())
                    .remove("pin")
                    .apply()
                pinInput.setText("")
                connectStatus.text = "Pareamento apagado. Leia o QR do PC para parear de novo."
                toast("Pareamento apagado")
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun showPairHelp(prefill: String?) {
        val texto = TextView(this).apply {
            text = "1. No PC, abra o QR de pareamento (ícone da bandeja ou tecla q no console).\n" +
                "2. Aponte a câmera do celular para o QR e abra o link.\n\n" +
                "Se a câmera não abrir, cole o link abaixo:"
            textSize = 14f
        }
        val campo = EditText(this).apply {
            hint = "localcontrol://…"
            setText(prefill.orEmpty())
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            maxLines = 3
        }
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(8), dp(20), 0)
            addView(texto)
            addView(campo)
        }
        AlertDialog.Builder(this)
            .setTitle("Parear por QR")
            .setView(layout)
            .setPositiveButton("Abrir link") { _, _ ->
                handlePairUri(campo.text.toString())
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (connected) {
            disconnect()
        } else if (keyboardVisible) {
            toggleKeyboard()
        } else {
            @Suppress("DEPRECATION")
            super.onBackPressed()
        }
    }

    private fun hideSystemBars() {
        @Suppress("DEPRECATION")
        val flags = View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
            View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_FULLSCREEN or
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = flags
    }

    // ------------------------------------------------------------ perfis de endereco

    /** Guarda o que esta nos campos no perfil ativo (host e porta). */
    private fun saveProfile() {
        prefs.edit()
            .putString("host_" + profileKeys[profile], hostInput.text.toString().trim())
            .putString("port_" + profileKeys[profile], portInput.text.toString().trim())
            .apply()
    }

    private fun switchProfile(novo: Int) {
        if (novo == profile) return
        saveProfile()
        profile = novo
        prefs.edit().putInt("perfil", novo).apply()
        hostInput.setText(prefs.getString("host_" + profileKeys[novo], ""))
        portInput.setText(prefs.getString("port_" + profileKeys[novo], "8765"))
        updateProfileButtons()
        toast(if (novo == 0) "Perfil Casa (mesma rede Wi-Fi)" else "Perfil Fora (Tailscale)")
    }

    private fun updateProfileButtons() {
        profileHomeBtn.setBackgroundResource(
            if (profile == 0) R.drawable.bg_btn_on else R.drawable.bg_btn
        )
        profileAwayBtn.setBackgroundResource(
            if (profile == 1) R.drawable.bg_btn_on else R.drawable.bg_btn
        )
    }

    // ------------------------------------------------------------ conexao

    /** Impressao digital da chave publica salva para o perfil ativo. */
    private fun spkiKey(): String = "spki_" + profileKeys[profile]

    /** Credencial exclusiva deste aparelho, recebida no pareamento por QR. */
    private fun deviceKey(): String = "device_" + profileKeys[profile]

    private fun loadDevice(): Pair<String, String>? {
        val raw = prefs.getString(deviceKey(), "").orEmpty()
        if (raw.isEmpty()) return null
        return try {
            val obj = JSONObject(raw)
            val id = obj.optString("id", "")
            val key = obj.optString("key", "")
            if (id.isNotEmpty() && key.isNotEmpty()) id to key else null
        } catch (_: Exception) {
            null
        }
    }

    private fun doConnect() {
        if (client != null || connecting) return

        val host = hostInput.text.toString().trim()
        if (host.isEmpty()) {
            toast("Informe o IP do PC")
            return
        }
        val port = portInput.text.toString().trim().toIntOrNull() ?: 8765
        val pin = pinInput.text.toString().trim()
        val device = loadDevice()
        if (pin.isEmpty() && device == null) {
            toast("Informe o PIN ou pareie pelo QR do PC")
            return
        }

        saveProfile()
        prefs.edit()
            .putString("host", host)
            .putString("port", port.toString())
            .apply()
        if (pin.isNotEmpty()) prefs.edit().putString("pin", pin).apply()

        val preset = presets[presetIndex]
        connectStatus.text = "Conectando em $host:$port…"
        connectBtn.isEnabled = false
        connecting = true

        val saved = prefs.getString(spkiKey(), "").orEmpty()
        if (saved.isNotEmpty()) {
            startClient(host, port, pin.ifEmpty { null }, preset, saved, device = device)
            return
        }

        // Sem chave salva: o QR e' o caminho recomendado. Se o usuario digitou o
        // PIN, faz a sondagem e pede confirmacao explicita da impressao digital.
        if (pin.isEmpty()) {
            connecting = false
            connectBtn.isEnabled = true
            connectStatus.text = "Sem pareamento salvo. Leia o QR do PC ou informe o PIN."
            return
        }
        connectStatus.text = "Verificando o certificado do PC…"
        Thread {
            try {
                val fingerprint = RemoteClient.probe(host, port)
                ui.post {
                    if (isFinishing || isDestroyed) return@post
                    showPairingDialog(host, port, pin, preset, fingerprint)
                }
            } catch (e: Exception) {
                ui.post {
                    if (isFinishing || isDestroyed) return@post
                    connecting = false
                    connectBtn.isEnabled = true
                    handleFailure(RemoteClient.describe(e, host))
                }
            }
        }.start()
    }

    private fun showPairingDialog(
        host: String,
        port: Int,
        pin: String,
        preset: Preset,
        fingerprint: String
    ) {
        AlertDialog.Builder(this)
            .setTitle("Confirmar PC")
            .setMessage(
                "Impressão digital da chave do PC:\n\n" +
                    LocalCrypto.formatFingerprint(fingerprint) +
                    "\n\nConfira com a que aparece no servidor do PC. " +
                    "Se for a primeira conexão, confirme. Se não bater, cancele."
            )
            .setPositiveButton("Confiar e conectar") { _, _ ->
                prefs.edit().putString(spkiKey(), fingerprint).apply()
                startClient(host, port, pin, preset, fingerprint)
            }
            .setNegativeButton("Cancelar") { _, _ ->
                connecting = false
                connectBtn.isEnabled = true
                connectStatus.text = "Conexão cancelada"
            }
            .setCancelable(false)
            .show()
    }

    private fun showMitmDialog(expected: String, actual: String, allowRepair: Boolean = true) {
        val builder = AlertDialog.Builder(this)
            .setTitle("Possível interceptação")
            .setMessage(
                "A chave pública do PC não confere com a esperada.\n\n" +
                    "Esperada:\n" + LocalCrypto.formatFingerprint(expected) + "\n\n" +
                    "Recebida:\n" + LocalCrypto.formatFingerprint(actual) + "\n\n" +
                    (if (allowRepair) {
                        "Alguém pode estar interceptando a conexão. Só re-pareie se " +
                            "você trocou o certificado do servidor de propósito."
                    } else {
                        "O QR não corresponde à chave já salva para este PC. Se você " +
                            "trocou o certificado do servidor de propósito, use " +
                            "\"Esquecer este PC\" e leia um novo QR. Caso contrário, " +
                            "não conecte."
                    })
            )
            .setNegativeButton("Bloquear") { _, _ ->
                connectStatus.text = "Conexão bloqueada: certificado diferente"
            }
            .setCancelable(false)

        if (allowRepair) {
            builder.setPositiveButton("Re-parear") { _, _ ->
                prefs.edit().putString(spkiKey(), actual).apply()
                doConnect()
            }
        }
        builder.show()
    }

    private fun startClient(
        host: String,
        port: Int,
        pin: String?,
        preset: Preset,
        fingerprint: String,
        pairToken: String? = null,
        device: Pair<String, String>? = null
    ) {
        val c = RemoteClient(
            host, port, pin, fingerprint, preset.width, preset.quality, preset.fps,
            pairToken, device?.first, device?.second
        )
        c.listener = object : RemoteClient.Listener {

            override fun onConnected() {
                if (client !== c) return
                connectBtn.isEnabled = true
                connectStatus.text = ""
                showRemote()
            }

            override fun onPaired(id: String, key: String, name: String) {
                if (client !== c) return
                // A credencial so e' gravada depois que o PC provou ter a chave
                // do QR e o pareamento foi aceito.
                prefs.edit()
                    .putString(spkiKey(), fingerprint)
                    .putString(
                        deviceKey(),
                        JSONObject()
                            .put("id", id)
                            .put("key", key)
                            .put("name", name)
                            .toString()
                    )
                    .apply()
                pendingPair = null
                connectStatus.text = "Pareado com ${name.ifEmpty { host }}"
                toast("Pareado com ${name.ifEmpty { host }}")
            }

            override fun onScreenInfo(info: JSONObject) {
                if (client !== c) return
                deviceName = info.optString("name", "")
                monitorCount = info.optInt("monitors", 1)
                monitorIndex = info.optInt("monitor", 1)
                monitorBtn.visibility = if (monitorCount > 1) View.VISIBLE else View.GONE
                monitorBtn.text = "MON $monitorIndex"
                updateStatus()
            }

            override fun onFrame(bitmap: Bitmap, cursorNx: Float, cursorNy: Float) {
                if (client !== c) return
                remoteView.setFrame(bitmap, cursorNx, cursorNy)
            }

            override fun onCursor(cursorNx: Float, cursorNy: Float) {
                if (client !== c) return
                remoteView.setCursor(cursorNx, cursorNy)
            }

            override fun onStats(fps: Int, latencyMs: Int) {
                if (client !== c) return
                fpsNow = fps
                this@MainActivity.latencyMs = latencyMs
                updateStatus()
            }

            override fun onError(message: String) {
                if (client !== c) return
                handleFailure(message)
            }

            override fun onFingerprintMismatch(expected: String, actual: String) {
                if (client !== c) return
                val eraPareamento = pendingPair != null
                pendingPair = null
                client = null
                c.stop()
                connected = false
                connecting = false
                connectBtn.isEnabled = true
                pairBtn.isEnabled = true
                resetTransientUi()
                requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                connectRoot.visibility = View.VISIBLE
                remoteRoot.visibility = View.GONE
                connectStatus.text = "Conexão bloqueada: a chave do PC não confere"
                showMitmDialog(expected, actual, allowRepair = !eraPareamento)
            }

            override fun onClosed() {
                if (client !== c) return
                handleFailure("conexão encerrada")
            }
        }

        client = c
        connecting = false
        c.start()
    }

    private fun showRemote() {
        connected = true
        connectRoot.visibility = View.GONE
        remoteRoot.visibility = View.VISIBLE
        remoteView.resetZoom()
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        resetTransientUi()
        setBarsVisible(true)
        updateStatus()
    }

    /** Fecha teclado virtual e painel de teclas para a proxima sessao comecar limpa. */
    private fun resetTransientUi() {
        closeKeyboard()
        keysPanel.visibility = View.GONE
        keysBtn.setBackgroundResource(R.drawable.bg_btn)
    }

    private fun handleFailure(message: String) {
        val c = client
        client = null
        c?.stop()
        connected = false
        connecting = false
        pendingPair = null
        connectBtn.isEnabled = true
        pairBtn.isEnabled = true
        resetTransientUi()
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        connectRoot.visibility = View.VISIBLE
        remoteRoot.visibility = View.GONE
        val dica = hintForFailure(message)
        connectStatus.text = if (dica != null) "Falha: $message\n$dica" else "Falha: $message"
    }

    /** Dica curta baseada no erro real e no endereco — so cita Tailscale quando faz sentido. */
    private fun hintForFailure(message: String): String? {
        val host = hostInput.text.toString().trim()
        val porta = portInput.text.toString().trim().ifEmpty { "8765" }
        val viaTailscale = host.startsWith("100.")

        return when {
            message.contains("muitas tentativas", ignoreCase = true) ->
                "Muitas tentativas erradas. Espere o tempo indicado e confira o PIN."

            message.contains("pin", ignoreCase = true) ||
                message.contains("autentic", ignoreCase = true) ->
                "O PIN tem que ser o mesmo configurado no PC (server.py --set-pin)."

            message.contains("TLS 1.3", ignoreCase = true) ->
                "TLS 1.3 exige Android 10 ou mais novo e o servidor atualizado."

            message.contains("certificado", ignoreCase = true) ||
                message.contains("intercept", ignoreCase = true) ->
                "A chave do PC não confere. Se você não trocou o certificado, não conecte."

            message.contains("TLS", ignoreCase = true) ->
                "O PC precisa estar rodando o servidor com TLS (sem --no-tls)."

            message.contains("recusada", ignoreCase = true) ||
                message.contains("tempo esgotado", ignoreCase = true) ->
                if (viaTailscale)
                    "Ligue o Tailscale no celular (sem economia de bateria) e confira se o PC aparece online."
                else
                    "No PC: o servidor esta rodando e o firewall liberado? Teste $host:$porta"

            message.contains("alcancavel", ignoreCase = true) ||
                message.contains("invalido", ignoreCase = true) ->
                if (viaTailscale)
                    "O IP 100.x so responde com o Tailscale ligado nos dois aparelhos."
                else
                    "O celular precisa estar no mesmo Wi-Fi do PC, ou use 127.0.0.1 no USB."

            else -> null
        }
    }

    private fun disconnect() {
        val c = client
        client = null
        c?.stop()
        connected = false
        connecting = false
        pendingPair = null
        connectBtn.isEnabled = true
        pairBtn.isEnabled = true
        remoteView.resetZoom()
        resetTransientUi()
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        connectRoot.visibility = View.VISIBLE
        remoteRoot.visibility = View.GONE
        connectStatus.text = "Desconectado"
    }

    private fun updateStatus() {
        if (!connected) return
        val parts = ArrayList<String>(4)
        if (deviceName.isNotEmpty()) parts.add(deviceName)
        parts.add("$fpsNow fps")
        parts.add("$latencyMs ms")
        statusText.text = parts.joinToString("  •  ")
    }

    // ------------------------------------------------------------ descoberta

    private fun scanNetwork() {
        if (scanning) return
        scanning = true
        scanBtn.isEnabled = false
        connectStatus.text = "Procurando PCs na rede…"
        Thread {
            val found = Discovery.scan(1600)
            ui.post {
                scanning = false
                scanBtn.isEnabled = true
                when {
                    found.isEmpty() -> connectStatus.text =
                        "Nenhum PC encontrado. Verifique o Wi-Fi ou use USB em 127.0.0.1"

                    found.size == 1 -> {
                        hostInput.setText(found[0].host)
                        portInput.setText(found[0].port.toString())
                        connectStatus.text = "Encontrado: ${found[0].name}"
                    }

                    else -> showDevicePicker(found)
                }
            }
        }.start()
    }

    private fun showDevicePicker(devices: List<Discovery.Device>) {
        val labels = devices.map { "${it.name}  (${it.host})" }.toTypedArray()
        AlertDialog.Builder(this)
            .setTitle("PCs encontrados")
            .setItems(labels) { _, which ->
                val device = devices[which]
                hostInput.setText(device.host)
                portInput.setText(device.port.toString())
                connectStatus.text = "Selecionado: ${device.name}"
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    // ------------------------------------------------------------ barra de acoes

    private fun setBarsVisible(visible: Boolean) {
        bottomBar.visibility = if (visible) View.VISIBLE else View.GONE
        showBtn.visibility = if (visible) View.GONE else View.VISIBLE
        if (!visible) keysPanel.visibility = View.GONE
        keysBtn.setBackgroundResource(if (keysPanel.visibility == View.VISIBLE) R.drawable.bg_btn_on else R.drawable.bg_btn)
    }

    private fun toggleKeysPanel() {
        val show = keysPanel.visibility != View.VISIBLE
        keysPanel.visibility = if (show) View.VISIBLE else View.GONE
        keysBtn.setBackgroundResource(if (show) R.drawable.bg_btn_on else R.drawable.bg_btn)
    }

    private fun updateModeLabel() {
        modeBtn.text = if (remoteView.mode == RemoteView.MODE_ABS) "Toque" else "Touchpad"
        modeBtn.setBackgroundResource(
            if (remoteView.mode == RemoteView.MODE_ABS) R.drawable.bg_btn else R.drawable.bg_btn_on
        )
    }

    private fun toggleMode() {
        val newMode = if (remoteView.mode == RemoteView.MODE_ABS) {
            RemoteView.MODE_TOUCHPAD
        } else {
            RemoteView.MODE_ABS
        }
        remoteView.mode = newMode
        prefs.edit().putInt("mode", newMode).apply()
        updateModeLabel()
        toast(
            if (newMode == RemoteView.MODE_ABS)
                "Modo toque: o cursor vai direto ao ponto tocado"
            else
                "Modo touchpad: arraste para mover o cursor"
        )
    }

    private fun cycleQuality() {
        presetIndex = (presetIndex + 1) % presets.size
        val preset = presets[presetIndex]
        qualityBtn.text = "Q: ${preset.label}"
        prefs.edit().putInt("preset", presetIndex).apply()
        client?.configure(preset.width, preset.quality, preset.fps)
    }

    private fun cycleMonitor() {
        if (monitorCount <= 1) return
        monitorIndex = if (monitorIndex >= monitorCount) 1 else monitorIndex + 1
        client?.selectMonitor(monitorIndex)
        monitorBtn.text = "MON $monitorIndex"
    }

    // ------------------------------------------------------------ teclado

    private fun setupKeyboard() {
        kbInput.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}

            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}

            override fun afterTextChanged(s: Editable?) {
                if (syncingText) return
                val text = s?.toString() ?: ""
                if (text.length > lastTyped.length && text.startsWith(lastTyped)) {
                    val added = text.substring(lastTyped.length)
                    if (added.isNotEmpty()) client?.text(added)
                } else if (text.length < lastTyped.length && lastTyped.startsWith(text)) {
                    val removed = lastTyped.length - text.length
                    repeat(removed) { client?.key("backspace", emptyList()) }
                } else if (text != lastTyped) {
                    repeat(lastTyped.length) { client?.key("backspace", emptyList()) }
                    if (text.isNotEmpty()) client?.text(text)
                }
                lastTyped = text

                if (text.length > 60) {
                    syncingText = true
                    kbInput.setText("")
                    syncingText = false
                    lastTyped = ""
                }
            }
        })
    }

    private fun toggleKeyboard() {
        if (!connected) return
        if (keyboardVisible) {
            closeKeyboard()
            return
        }
        kbInput.setText("")
        lastTyped = ""
        kbInput.requestFocus()
        val imm = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
        imm.showSoftInput(kbInput, InputMethodManager.SHOW_IMPLICIT)
        keyboardVisible = true
        kbBtn.setBackgroundResource(R.drawable.bg_btn_on)
    }

    private fun closeKeyboard() {
        if (!keyboardVisible) return
        val imm = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
        imm.hideSoftInputFromWindow(kbInput.windowToken, 0)
        kbInput.clearFocus()
        keyboardVisible = false
        kbBtn.setBackgroundResource(R.drawable.bg_btn)
    }

    // ------------------------------------------------------------ teclas especiais

    private fun buildKeys() {
        keysRow.removeAllViews()
        modButtons.clear()

        for ((label, key) in listOf("Ctrl" to "ctrl", "Alt" to "alt", "Shift" to "shift")) {
            val button = keyButton(label, key, true)
            modButtons[key] = button
            keysRow.addView(button)
        }

        val keys = listOf(
            "Esc" to "esc",
            "Tab" to "tab",
            "⏎" to "enter",
            "⌫" to "backspace",
            "Del" to "delete",
            "Win" to "win",
            "PrtSc" to "printscreen",
            "Space" to "space",
            "←" to "left",
            "↑" to "up",
            "↓" to "down",
            "→" to "right",
            "F5" to "f5",
            "F11" to "f11"
        )
        for ((label, key) in keys) {
            keysRow.addView(keyButton(label, key, false))
        }
    }

    private fun keyButton(label: String, key: String, isModifier: Boolean): TextView {
        val view = TextView(this, null, 0, R.style.RemoteButton)
        view.text = label
        view.setPadding(dp(10), 0, dp(10), 0)
        val params = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(33))
        params.marginStart = dp(3)
        params.marginEnd = dp(3)
        params.topMargin = dp(3)
        params.bottomMargin = dp(3)
        view.layoutParams = params
        view.setOnClickListener { onSpecialKey(key, isModifier) }
        return view
    }

    private fun onSpecialKey(key: String, isModifier: Boolean) {
        if (isModifier) {
            if (!sticky.add(key)) sticky.remove(key)
            refreshModifiers()
            return
        }
        client?.key(key, sticky.toList())
        sticky.clear()
        refreshModifiers()
    }

    private fun refreshModifiers() {
        for ((key, view) in modButtons) {
            view.setBackgroundResource(
                if (key in sticky) R.drawable.bg_btn_on else R.drawable.bg_btn
            )
        }
    }

    // ------------------------------------------------------------ RemoteView.Listener

    override fun onMoveAbs(nx: Float, ny: Float) {
        client?.moveAbs(nx, ny)
    }

    override fun onMoveRel(dx: Float, dy: Float) {
        client?.moveRel(dx, dy)
    }

    override fun onButton(btn: String, down: Boolean) {
        client?.button(btn, down)
    }

    override fun onClick(btn: String, count: Int) {
        client?.click(btn, count)
    }

    override fun onScroll(dy: Float, dx: Float) {
        client?.scroll(dy, dx)
    }

    // ------------------------------------------------------------ util

    private var lastToast: Toast? = null

    private fun toast(message: String) {
        lastToast?.cancel()
        lastToast = Toast.makeText(this, message, Toast.LENGTH_SHORT).also { it.show() }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
