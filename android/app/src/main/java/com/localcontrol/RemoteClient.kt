package com.localcontrol

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.ByteBuffer
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket

/**
 * Cliente do servidor do PC.
 *
 * O transporte e' TLS 1.3 com pinning da chave publica (SPKI): o app so fala
 * com o PC cuja impressao digital foi confirmada no pareamento. Dentro do TLS,
 * o PIN nunca trafega — o app responde ao nonce do servidor com
 * HMAC-SHA256(PBKDF2(pin), nonce).
 *
 * No primeiro pareamento por QR, o app usa o token do QR (tambem por HMAC) e
 * recebe do servidor uma chave exclusiva do aparelho; nas conexoes seguintes
 * autentica com essa chave, sem PIN.
 *
 * Uma thread le os quadros (JPEG) e decodifica em dois bitmaps alternados,
 * outra thread envia os eventos de entrada e uma terceira mede a latencia.
 */
class RemoteClient(
    private val host: String,
    private val port: Int,
    private val pin: String?,
    private val expectedFingerprint: String?,
    var width: Int,
    var quality: Int,
    var fps: Int,
    private val pairToken: String? = null,
    private val deviceId: String? = null,
    private val deviceKey: String? = null
) {

    interface Listener {
        fun onConnected()
        fun onScreenInfo(info: JSONObject)
        fun onFrame(bitmap: Bitmap, cursorNx: Float, cursorNy: Float)
        fun onCursor(cursorNx: Float, cursorNy: Float)
        fun onStats(fps: Int, latencyMs: Int)
        fun onError(message: String)
        fun onClosed()

        /** Pareamento por QR concluido: guarde id+chave para as proximas conexoes. */
        fun onPaired(id: String, key: String, name: String) {}

        /** A chave do PC mudou (possivel MITM). Nao conecte sem acao do usuario. */
        fun onFingerprintMismatch(expected: String, actual: String) {}
    }

    var listener: Listener? = null

    @Volatile
    private var running = false
    private var socket: Socket? = null
    private var out: DataOutputStream? = null
    private val queue = LinkedBlockingQueue<ByteArray>()

    private var reader: Thread? = null
    private var writer: Thread? = null
    private var pinger: Thread? = null

    private val framePending = AtomicBoolean(false)
    private var bufA: Bitmap? = null
    private var bufB: Bitmap? = null
    private var useA = true

    private var fpsFrames = 0
    private var fpsMark = 0L
    private var latency = 0
    private var handshakeDone = false

    val isRunning: Boolean get() = running

    // ------------------------------------------------------------ ciclo de vida

    fun start() {
        if (running) return
        running = true
        fpsMark = SystemClock.elapsedRealtime()
        reader = Thread({ runLoop() }, "lc-reader").apply {
            isDaemon = true
            start()
        }
    }

    fun stop() {
        running = false
        queue.clear()
        try {
            socket?.close()
        } catch (_: Exception) {
        }
        writer?.interrupt()
        pinger?.interrupt()
    }

    private fun runLoop() {
        var s: Socket? = null
        try {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
                throw IOException("TLS 1.3 exige Android 10 ou mais novo")
            }

            val tls = openTls()
            s = tls
            socket = tls

            val input = DataInputStream(BufferedInputStream(tls.getInputStream(), 512 * 1024))
            out = DataOutputStream(BufferedOutputStream(tls.getOutputStream(), 32 * 1024))

            // 1) desafio: nonce novo por conexao (impede reaproveitar o MAC)
            val challenge = readChallenge(input) ?: return

            val nonce = LocalCrypto.base64Decode(challenge.getString("nonce"))

            writer = Thread({ writeLoop() }, "lc-writer").apply {
                isDaemon = true
                start()
            }

            // 2) HELLO: PIN, token de pareamento ou chave do aparelho.
            //    Nenhum segredo e enviado: so o HMAC do nonce.
            val hello = JSONObject()
                .put("v", 3)
                .put("name", Build.MODEL)
                .put("width", width)
                .put("quality", quality)
                .put("fps", fps)

            val token = pairToken
            val savedId = deviceId
            val savedKey = deviceKey
            when {
                !token.isNullOrEmpty() -> {
                    val raw = token.toByteArray(Charsets.UTF_8)
                    hello.put("pid", Pairing.tokenId(token))
                    hello.put(
                        "mac",
                        LocalCrypto.base64Encode(LocalCrypto.hmacSha256(raw, nonce))
                    )
                }

                !savedId.isNullOrEmpty() && !savedKey.isNullOrEmpty() -> {
                    val raw = LocalCrypto.base64Decode(savedKey)
                    hello.put("device", savedId)
                    hello.put(
                        "mac",
                        LocalCrypto.base64Encode(LocalCrypto.hmacSha256(raw, nonce))
                    )
                }

                !pin.isNullOrEmpty() -> {
                    val salt = LocalCrypto.base64Decode(challenge.getString("salt"))
                    val iterations = challenge.optInt("iter", 210_000)
                    val key = LocalCrypto.pbkdf2Sha256(
                        pin.toByteArray(Charsets.UTF_8), salt, iterations, 32
                    )
                    hello.put(
                        "mac",
                        LocalCrypto.base64Encode(LocalCrypto.hmacSha256(key, nonce))
                    )
                }

                else -> throw IOException("sem PIN e sem pareamento: use o QR do PC")
            }
            sendJson(TYPE_HELLO, hello)

            // so mede latencia depois do handshake, senao o ping chega antes do HELLO
            pinger = Thread({ pingLoop() }, "lc-ping").apply {
                isDaemon = true
                start()
            }

            while (running) {
                val len = input.readInt()
                if (len < 1 || len > MAX_INCOMING) throw IOException("quadro invalido ($len)")
                val type = input.readUnsignedByte()
                val payload = ByteArray(len - 1)
                input.readFully(payload)

                when (type) {
                    TYPE_PAIR_OK -> {
                        val info = JSONObject(String(payload, Charsets.UTF_8))
                        val id = info.optString("id", "")
                        val key = info.optString("key", "")
                        if (id.isNotEmpty() && key.isNotEmpty()) {
                            val nome = info.optString("name", "")
                            post { listener?.onPaired(id, key, nome) }
                        }
                    }

                    TYPE_SCREEN -> {
                        val info = JSONObject(String(payload, Charsets.UTF_8))
                        val first = !handshakeDone
                        handshakeDone = true
                        post {
                            if (first) listener?.onConnected()
                            listener?.onScreenInfo(info)
                        }
                    }

                    TYPE_INFO -> {
                        val info = JSONObject(String(payload, Charsets.UTF_8))
                        val err = info.optString("error", "")
                        if (err.isNotEmpty()) {
                            post { listener?.onError(err) }
                            break
                        }
                    }

                    TYPE_VIDEO -> handleVideo(payload)

                    TYPE_CURSOR -> {
                        if (payload.size >= 4) {
                            val nx = (((payload[0].toInt() and 0xFF) shl 8) or
                                (payload[1].toInt() and 0xFF)) / 65535f
                            val ny = (((payload[2].toInt() and 0xFF) shl 8) or
                                (payload[3].toInt() and 0xFF)) / 65535f
                            post { listener?.onCursor(nx, ny) }
                        }
                    }

                    TYPE_PONG -> {
                        val ts = try {
                            JSONObject(String(payload, Charsets.UTF_8)).optLong("ts", 0)
                        } catch (_: Exception) {
                            0
                        }
                        if (ts > 0) latency = (SystemClock.elapsedRealtime() - ts).toInt()
                    }
                }
            }
        } catch (e: Exception) {
            val pinFailure = findPinningFailure(e)
            if (running) {
                if (pinFailure != null) {
                    post { listener?.onFingerprintMismatch(pinFailure.expected, pinFailure.actual) }
                } else {
                    post { listener?.onError(describe(e, host)) }
                }
            }
        } finally {
            running = false
            try {
                s?.close()
            } catch (_: Exception) {
            }
            queue.clear()
            post { listener?.onClosed() }
        }
    }

    /** Abre o socket TLS 1.3 com pinning da SPKI. */
    private fun openTls(): SSLSocket {
        val ssl = tlsContext(expectedFingerprint).socketFactory.createSocket() as SSLSocket
        ssl.tcpNoDelay = true
        ssl.receiveBufferSize = 1 shl 20
        ssl.connect(InetSocketAddress(host, port), 6000)
        ssl.soTimeout = 15000
        val params = ssl.sslParameters
        params.protocols = arrayOf("TLSv1.3")
        ssl.sslParameters = params
        ssl.startHandshake()
        return ssl
    }

    /** Le a primeira mensagem: o desafio (ou um erro, como bloqueio por IP). */
    private fun readChallenge(input: DataInputStream): JSONObject? {
        while (running) {
            val len = input.readInt()
            if (len < 1 || len > MAX_INCOMING) throw IOException("mensagem invalida ($len)")
            val type = input.readUnsignedByte()
            val payload = ByteArray(len - 1)
            input.readFully(payload)

            when (type) {
                TYPE_CHALLENGE -> {
                    val challenge = JSONObject(String(payload, Charsets.UTF_8))
                    if (!challenge.optBoolean("auth", true)) {
                        throw IOException("o PC nao tem PIN configurado")
                    }
                    return challenge
                }

                TYPE_INFO -> {
                    val info = JSONObject(String(payload, Charsets.UTF_8))
                    post { listener?.onError(info.optString("error", "erro do servidor")) }
                    return null
                }

                else -> throw IOException("resposta inesperada do servidor (0x%02x)".format(type))
            }
        }
        return null
    }

    private fun writeLoop() {
        try {
            while (running) {
                val data = queue.poll(500, TimeUnit.MILLISECONDS) ?: continue
                val o = out ?: break
                o.write(data)
                o.flush()
            }
        } catch (_: Exception) {
            // socket fechado: a thread de leitura avisa a Activity
        }
    }

    private fun pingLoop() {
        while (running) {
            try {
                Thread.sleep(700)
            } catch (_: InterruptedException) {
                return
            }
            if (!running) return
            sendInput("{\"t\":\"ping\",\"ts\":${SystemClock.elapsedRealtime()}}")
            try {
                Thread.sleep(1500)
            } catch (_: InterruptedException) {
                return
            }
        }
    }

    // ------------------------------------------------------------ video

    private fun handleVideo(payload: ByteArray) {
        if (payload.size < 8) return
        val cx = (((payload[0].toInt() and 0xFF) shl 8) or (payload[1].toInt() and 0xFF)) / 65535f
        val cy = (((payload[2].toInt() and 0xFF) shl 8) or (payload[3].toInt() and 0xFF)) / 65535f

        if (framePending.get()) return

        val bmp = decode(payload, 4, payload.size - 4) ?: return
        if (framePending.compareAndSet(false, true)) {
            post {
                listener?.onFrame(bmp, cx, cy)
                framePending.set(false)
            }
        }

        fpsFrames++
        val now = SystemClock.elapsedRealtime()
        if (now - fpsMark >= 1000) {
            val value = (fpsFrames * 1000f / (now - fpsMark)).toInt()
            fpsFrames = 0
            fpsMark = now
            val ms = latency
            post { listener?.onStats(value, ms) }
        }
    }

    private fun decode(data: ByteArray, offset: Int, length: Int): Bitmap? {
        val reuse = if (useA) bufA else bufB
        val opts = BitmapFactory.Options().apply {
            inPreferredConfig = Bitmap.Config.ARGB_8888
            inMutable = true
            inTempStorage = ByteArray(16 * 1024)
            if (reuse != null && !reuse.isRecycled) inBitmap = reuse
        }
        var bmp: Bitmap? = try {
            BitmapFactory.decodeByteArray(data, offset, length, opts)
        } catch (_: IllegalArgumentException) {
            opts.inBitmap = null
            BitmapFactory.decodeByteArray(data, offset, length, opts)
        } ?: return null

        if (useA) bufA = bmp else bufB = bmp
        useA = !useA
        return bmp
    }

    // ------------------------------------------------------------ entrada

    private fun sendInput(json: String) {
        sendFrame(TYPE_INPUT, json.toByteArray(Charsets.UTF_8))
    }

    private fun sendJson(type: Int, obj: JSONObject) {
        sendFrame(type, obj.toString().toByteArray(Charsets.UTF_8))
    }

    private fun sendFrame(type: Int, payload: ByteArray) {
        if (!running && type != TYPE_HELLO) return
        val buf = ByteBuffer.allocate(5 + payload.size)
        buf.putInt(1 + payload.size)
        buf.put(type.toByte())
        buf.put(payload)
        queue.offer(buf.array())
        if (queue.size > 400) queue.clear()
    }

    fun moveAbs(nx: Float, ny: Float) {
        sendInput("{\"t\":\"m\",\"x\":$nx,\"y\":$ny}")
    }

    fun moveRel(dx: Float, dy: Float) {
        sendInput("{\"t\":\"mr\",\"dx\":$dx,\"dy\":$dy}")
    }

    fun button(btn: String, down: Boolean) {
        sendInput("{\"t\":\"b\",\"btn\":\"$btn\",\"down\":$down}")
    }

    fun click(btn: String, count: Int) {
        sendInput("{\"t\":\"c\",\"btn\":\"$btn\",\"count\":$count}")
    }

    fun scroll(dy: Float, dx: Float) {
        sendInput("{\"t\":\"s\",\"dy\":$dy,\"dx\":$dx}")
    }

    fun key(key: String, mods: List<String>) {
        val modsJson = mods.joinToString(",") { "\"$it\"" }
        sendInput("{\"t\":\"k\",\"key\":\"$key\",\"mods\":[$modsJson]}")
    }

    fun text(value: String) {
        val escaped = value
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        sendInput("{\"t\":\"kt\",\"text\":\"$escaped\"}")
    }

    fun configure(newWidth: Int, newQuality: Int, newFps: Int) {
        width = newWidth
        quality = newQuality
        fps = newFps
        sendInput("{\"t\":\"r\",\"width\":$newWidth,\"quality\":$newQuality,\"fps\":$newFps}")
    }

    fun selectMonitor(index: Int) {
        sendInput("{\"t\":\"mon\",\"i\":$index}")
    }

    // ------------------------------------------------------------ util

    private val main = Handler(Looper.getMainLooper())

    private fun post(block: () -> Unit) {
        main.post(block)
    }

    companion object {
        const val TYPE_VIDEO = 0x01
        const val TYPE_SCREEN = 0x02
        const val TYPE_CURSOR = 0x03
        const val TYPE_HELLO = 0x10
        const val TYPE_INPUT = 0x11
        const val TYPE_INFO = 0x12
        const val TYPE_PING = 0x13
        const val TYPE_PONG = 0x14
        const val TYPE_CHALLENGE = 0x15
        const val TYPE_PAIR_OK = 0x16

        private const val MAX_INCOMING = 16 * 1024 * 1024

        private fun tlsContext(expected: String?): SSLContext {
            val ctx = SSLContext.getInstance("TLS")
            ctx.init(null, arrayOf(PinningTrustManager(expected)), SecureRandom())
            return ctx
        }

        /**
         * Conecta so para ler a SPKI do servidor (primeiro pareamento).
         * Nao autentica e nao envia nada.
         */
        fun probe(host: String, port: Int, timeoutMs: Int = 6000): String {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
                throw IOException("TLS 1.3 exige Android 10 ou mais novo")
            }
            val ssl = tlsContext(null).socketFactory.createSocket() as SSLSocket
            try {
                ssl.connect(InetSocketAddress(host, port), timeoutMs)
                ssl.soTimeout = timeoutMs
                val params = ssl.sslParameters
                params.protocols = arrayOf("TLSv1.3")
                ssl.sslParameters = params
                ssl.startHandshake()
                val cert = ssl.session.peerCertificates.firstOrNull() as? X509Certificate
                    ?: throw IOException("o PC nao apresentou certificado")
                return LocalCrypto.spkiFingerprint(cert)
            } finally {
                try {
                    ssl.close()
                } catch (_: Exception) {
                }
            }
        }

        private fun findPinningFailure(error: Throwable): PinningException? {
            var atual: Throwable? = error
            var depth = 0
            while (atual != null && depth < 8) {
                if (atual is PinningException) return atual
                atual = atual.cause
                depth++
            }
            return null
        }

        /** Traduz a falha de rede para algo que o usuario entenda (sem culpar o Tailscale). */
        fun describe(e: Exception, host: String): String = when (e) {
            is java.net.SocketTimeoutException ->
                "o PC nao respondeu (tempo esgotado)"
            is java.net.ConnectException ->
                "conexao recusada: o servidor esta rodando no PC?"
            is java.net.NoRouteToHostException ->
                "endereco inalcancavel: IP errado ou aparelho em outra rede"
            is java.net.UnknownHostException ->
                "endereco invalido: ${e.message ?: host}"
            is javax.net.ssl.SSLHandshakeException -> {
                val detalhe = e.cause?.message ?: e.message.orEmpty()
                if (detalhe.contains("protocol", true) || detalhe.contains("TLS", true))
                    "o PC nao aceitou TLS 1.3 (servidor atualizado e Android 10+)"
                else
                    "falha no TLS: ${detalhe.ifEmpty { "handshake" }}"
            }
            is javax.net.ssl.SSLException ->
                "falha no TLS: ${e.message ?: "conexao segura"}"
            is java.net.SocketException -> {
                val m = e.message.orEmpty()
                if (m.contains("reset", true) || m.contains("abort", true))
                    "o PC encerrou a conexao"
                else
                    m.ifEmpty { "conexao interrompida" }
            }
            else -> e.message ?: e.javaClass.simpleName
        }
    }
}
