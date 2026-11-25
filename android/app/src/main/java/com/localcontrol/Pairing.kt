package com.localcontrol

import android.net.Uri
import android.util.Base64

/**
 * Link do QR de pareamento:
 *
 *   localcontrol://192.168.0.10:8765?fp=<SPKI base64url>&t=<token>&n=<PC>
 *
 * O `fp` e a impressao digital da chave publica (SPKI) do PC, o mesmo valor
 * que o pinning usa. O `t` e um token de uso unico, valido por poucos minutos:
 * ele NAO e o PIN e deixa de funcionar depois do primeiro pareamento.
 */
object Pairing {

    const val SCHEME = "localcontrol"
    private const val MAX_TOKEN = 200
    private const val MIN_TOKEN = 20

    data class Info(
        val host: String,
        val port: Int,
        val fingerprint: String,
        val token: String,
        val name: String
    )

    fun parse(raw: String?): Info? {
        if (raw.isNullOrBlank()) return null
        val uri = try {
            Uri.parse(raw.trim())
        } catch (_: Exception) {
            return null
        }
        if (!uri.scheme.equals(SCHEME, ignoreCase = true)) return null

        val host: String
        val port: Int
        if (uri.host.equals("pair", ignoreCase = true)) {
            // formato alternativo: localcontrol://pair?host=...&port=...
            host = uri.getQueryParameter("host")?.trim().orEmpty()
            port = uri.getQueryParameter("port")?.toIntOrNull() ?: 8765
        } else {
            host = uri.host?.trim().orEmpty()
            port = if (uri.port > 0) {
                uri.port
            } else {
                uri.getQueryParameter("port")?.toIntOrNull() ?: 8765
            }
        }

        val fingerprint = fingerprintFromUrl(uri.getQueryParameter("fp").orEmpty())
            ?: return null
        val token = uri.getQueryParameter("t")?.trim().orEmpty()
        val name = uri.getQueryParameter("n").orEmpty()

        if (host.isEmpty() || port !in 1..65535) return null
        if (token.length !in MIN_TOKEN..MAX_TOKEN) return null
        // o token precisa ser ASCII seguro para URL (base64url)
        if (!token.all { it.isLetterOrDigit() || it == '-' || it == '_' }) return null

        return Info(host, port, fingerprint, token, name)
    }

    /** Converte o `fp` do link (base64url, sem padding) para o base64 do pinning. */
    fun fingerprintFromUrl(value: String): String? {
        if (value.isEmpty()) return null
        val normal = value.replace('-', '+').replace('_', '/')
        val padded = normal + "=".repeat((4 - normal.length % 4) % 4)
        return try {
            val raw = Base64.decode(padded, Base64.DEFAULT)
            if (raw.size != 32) null
            else Base64.encodeToString(raw, Base64.NO_WRAP)
        } catch (_: Exception) {
            null
        }
    }

    /** Identificador publico do token, igual ao `pid` calculado pelo servidor. */
    fun tokenId(token: String): String {
        val digest = LocalCrypto.sha256(token.toByteArray(Charsets.UTF_8))
        val hex = StringBuilder(digest.size * 2)
        for (byte in digest) {
            val value = byte.toInt() and 0xFF
            hex.append("0123456789abcdef"[value ushr 4])
            hex.append("0123456789abcdef"[value and 0x0F])
        }
        return hex.substring(0, 32)
    }
}
