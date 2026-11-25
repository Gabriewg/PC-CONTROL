// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.gabriewg.poltergeist

import android.util.Base64
import java.security.MessageDigest
import java.security.cert.X509Certificate
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Primitivas usadas no handshake com o servidor.
 *
 * O PIN nunca sai do aparelho: ele vira uma chave com PBKDF2 e essa chave
 * assina o nonce do servidor (HMAC-SHA256).
 */
object LocalCrypto {

    fun base64Encode(raw: ByteArray): String = Base64.encodeToString(raw, Base64.NO_WRAP)

    fun base64Decode(text: String): ByteArray = Base64.decode(text, Base64.DEFAULT)

    fun sha256(data: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(data)

    fun hmacSha256(key: ByteArray, data: ByteArray): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        return mac.doFinal(data)
    }

    /**
     * Impressao digital da chave publica (SPKI), em base64.
     *
     * `X509Certificate.publicKey.encoded` ja devolve o SubjectPublicKeyInfo em
     * DER, que e exatamente o que o servidor calcula. Pinar a chave (e nao o
     * certificado inteiro) permite renovar o certificado sem re-parear.
     */
    fun spkiFingerprint(cert: X509Certificate): String =
        base64Encode(sha256(cert.publicKey.encoded))

    fun formatFingerprint(fingerprint: String): String {
        val limpo = fingerprint.replace(" ", "")
        return limpo.chunked(4).joinToString(" ")
    }

    /**
     * PBKDF2-HMAC-SHA256 implementado a mao.
     *
     * `PBKDF2WithHmacSHA256` so existe a partir da API 26, e o app suporta a 24.
     * A saida e identica a de hashlib.pbkdf2_hmac("sha256", ...) do Python.
     */
    fun pbkdf2Sha256(
        password: ByteArray,
        salt: ByteArray,
        iterations: Int,
        keyLength: Int
    ): ByteArray {
        require(iterations > 0) { "iteracoes invalidas" }
        require(keyLength > 0) { "tamanho de chave invalido" }

        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(password, "HmacSHA256"))
        val hLen = mac.macLength
        val blocks = (keyLength + hLen - 1) / hLen
        val out = ByteArray(blocks * hLen)
        val index = ByteArray(4)

        for (block in 1..blocks) {
            index[0] = (block ushr 24).toByte()
            index[1] = (block ushr 16).toByte()
            index[2] = (block ushr 8).toByte()
            index[3] = block.toByte()

            mac.update(salt)
            mac.update(index)
            var u = mac.doFinal()
            val t = u.copyOf()
            for (i in 2..iterations) {
                u = mac.doFinal(u)
                for (j in t.indices) t[j] = (t[j].toInt() xor u[j].toInt()).toByte()
            }
            System.arraycopy(t, 0, out, (block - 1) * hLen, hLen)
        }

        return if (out.size == keyLength) out else out.copyOf(keyLength)
    }
}
