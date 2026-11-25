// SPDX-License-Identifier: AGPL-3.0-or-later
package com.localcontrol

import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.X509TrustManager

/** O certificado apresentado nao tem a mesma chave publica da ultima vez. */
class PinningException(val expected: String, val actual: String) :
    CertificateException("a chave publica do servidor mudou")

/**
 * Confia apenas no certificado cuja chave publica (SPKI) confere com a
 * impressao digital salva no pareamento.
 *
 * Nao existe "confiar em tudo": quando a digital nao bate, a conexao e
 * derrubada com [PinningException] para a Activity mostrar o aviso de MITM.
 * A verificacao de hostname nao e desligada globalmente; o pinning da chave
 * e o que autentica o servidor (ele e acessado por IP, sem DNS).
 */
class PinningTrustManager(private val expected: String?) : X509TrustManager {

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        throw CertificateException("o cliente nao autentica por certificado")
    }

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val cert = chain?.firstOrNull() ?: throw CertificateException("servidor sem certificado")
        val actual = LocalCrypto.spkiFingerprint(cert)
        // Sem digital salva (sondagem do primeiro pareamento) qualquer
        // certificado e aceito; a Activity so conecta de verdade depois que o
        // usuario confirma a impressao digital.
        if (expected.isNullOrEmpty()) return
        if (actual != expected) throw PinningException(expected, actual)
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}
