package com.capsstream.tv

import android.content.Context
import android.net.wifi.WifiManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.URL

object DiscoveryHelper {

    private const val DEFAULT_PORT = 8000
    private const val PROBE_TIMEOUT_MS = 1200

    /**
     * Attempts to locate an active CapsStream server on the local subnet.
     * Returns the base URL (e.g. "http://192.168.1.50:8000") or null if not found.
     */
    suspend fun discoverServer(context: Context): String? = withContext(Dispatchers.IO) {
        val baseIp = getSubnetPrefix(context) ?: return@withContext null

        // 1. Probe common host addresses first (.1, .2, .100, .101, etc.)
        val priorityHosts = listOf(1, 2, 3, 4, 10, 20, 50, 100, 101, 102, 150, 200)
        for (lastOctet in priorityHosts) {
            val candidateIp = "$baseIp.$lastOctet"
            if (isCapsStreamServer(candidateIp, DEFAULT_PORT)) {
                return@withContext "http://$candidateIp:$DEFAULT_PORT"
            }
        }

        // 2. Scan remaining active subnet addresses
        for (i in 5..254) {
            if (priorityHosts.contains(i)) continue
            val candidateIp = "$baseIp.$i"
            if (isCapsStreamServer(candidateIp, DEFAULT_PORT)) {
                return@withContext "http://$candidateIp:$DEFAULT_PORT"
            }
        }

        null
    }

    /**
     * Checks whether an endpoint is a live CapsStream instance.
     */
    suspend fun isCapsStreamServer(ip: String, port: Int): Boolean = withContext(Dispatchers.IO) {
        try {
            val endpoint = URL("http://$ip:$port/")
            val conn = (endpoint.openConnection() as HttpURLConnection).apply {
                connectTimeout = PROBE_TIMEOUT_MS
                readTimeout = PROBE_TIMEOUT_MS
                requestMethod = "GET"
                setRequestProperty("User-Agent", "CapsStream-AndroidTV")
            }
            conn.connect()
            val code = conn.responseCode
            conn.disconnect()
            code in 200..499
        } catch (e: Exception) {
            false
        }
    }

    private fun getSubnetPrefix(context: Context): String? {
        return try {
            val interfaces = java.net.NetworkInterface.getNetworkInterfaces()
            if (interfaces != null) {
                for (intf in interfaces.asSequence()) {
                    if (intf.isLoopback || !intf.isUp) continue
                    for (addr in intf.inetAddresses.asSequence()) {
                        if (!addr.isLoopback && addr is java.net.Inet4Address) {
                            val host = addr.hostAddress ?: continue
                            val parts = host.split(".")
                            if (parts.size == 4 && parts[0] != "127") {
                                return "${parts[0]}.${parts[1]}.${parts[2]}"
                            }
                        }
                    }
                }
            }
            val wm = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            val ipInt = wm?.connectionInfo?.ipAddress ?: 0
            if (ipInt == 0) return "192.168.1"
            val ip = InetAddress.getByAddress(
                byteArrayOf(
                    (ipInt and 0xff).toByte(),
                    (ipInt shr 8 and 0xff).toByte(),
                    (ipInt shr 16 and 0xff).toByte(),
                    (ipInt shr 24 and 0xff).toByte()
                )
            ).hostAddress ?: return "192.168.1"

            val parts = ip.split(".")
            if (parts.size == 4) "${parts[0]}.${parts[1]}.${parts[2]}" else "192.168.1"
        } catch (e: Exception) {
            "192.168.1"
        }
    }
}
