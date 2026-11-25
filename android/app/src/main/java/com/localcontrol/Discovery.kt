// SPDX-License-Identifier: AGPL-3.0-or-later
package com.localcontrol

import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InterfaceAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException

/** Descobre servidores na mesma rede via UDP broadcast. */
object Discovery {

    const val PORT = 8766
    private const val MAGIC = "LOCALCONTROL_DISCOVER"

    data class Device(val name: String, val host: String, val port: Int)

    fun scan(timeoutMs: Int = 1500): List<Device> {
        val found = LinkedHashMap<String, Device>()
        var socket: DatagramSocket? = null
        try {
            socket = DatagramSocket().apply {
                broadcast = true
                soTimeout = 200
            }
            val payload = MAGIC.toByteArray()

            for (address in broadcastAddresses()) {
                try {
                    socket.send(DatagramPacket(payload, payload.size, address, PORT))
                } catch (_: Exception) {
                }
            }

            val deadline = System.currentTimeMillis() + timeoutMs
            val buffer = ByteArray(1024)
            while (System.currentTimeMillis() < deadline) {
                try {
                    val packet = DatagramPacket(buffer, buffer.size)
                    socket.receive(packet)
                    val json = JSONObject(String(packet.data, 0, packet.length, Charsets.UTF_8))
                    val host = packet.address?.hostAddress ?: continue
                    val name = json.optString("name", host)
                    found[host] = Device(name, host, json.optInt("port", 8765))
                } catch (_: SocketTimeoutException) {
                } catch (_: Exception) {
                }
            }
        } catch (_: Exception) {
        } finally {
            try {
                socket?.close()
            } catch (_: Exception) {
            }
        }
        return found.values.toList()
    }

    private fun broadcastAddresses(): Set<InetAddress> {
        val list = LinkedHashSet<InetAddress>()
        try {
            list.add(InetAddress.getByName("255.255.255.255"))
        } catch (_: Exception) {
        }
        try {
            for (nic in NetworkInterface.getNetworkInterfaces()) {
                if (!nic.isUp || nic.isLoopback) continue
                for (info: InterfaceAddress in nic.interfaceAddresses) {
                    info.broadcast?.let { list.add(it) }
                }
            }
        } catch (_: Exception) {
        }
        return list
    }
}
