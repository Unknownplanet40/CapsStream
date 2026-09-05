package com.capsstream.tv

import android.content.Context
import android.net.wifi.WifiManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.URL

object DiscoveryHelper {

    private const val DEFAULT_PORT = 8000
    private const val UDP_DISCOVERY_PORT = 8001
    private const val PROBE_TIMEOUT_MS = 900

    /**
     * Attempts to locate an active CapsStream server on the local network.
     * 1. First tries instant UDP broadcast on port 8001 (returns in ~15ms).
     * 2. Fallbacks to fast parallel subnet HTTP probing on /api/health (returns in ~1s).
     */
    suspend fun discoverServer(context: Context): String? = withContext(Dispatchers.IO) {
        // 1. Instant UDP broadcast discovery
        val udpDiscovered = probeUdpBroadcast()
        if (udpDiscovered != null) {
            return@withContext udpDiscovered
        }

        // 2. Subnet candidate discovery
        val prefixes = getSubnetPrefixes(context)
        if (prefixes.isEmpty()) return@withContext null

        val priorityOctets = listOf(2, 1, 3, 4, 10, 20, 50, 100, 101, 102, 150, 200)
        val priorityIps = mutableListOf<String>()

        for (prefix in prefixes) {
            if (prefix == "10.0.2") {
                // Support Android emulator host loopback
                priorityIps.add("10.0.2.2")
            }
            for (lastOctet in priorityOctets) {
                priorityIps.add("$prefix.$lastOctet")
            }
        }

        // Fast parallel probe on priority candidates
        val priorityResult = probeBatchInParallel(priorityIps.distinct(), DEFAULT_PORT, PROBE_TIMEOUT_MS)
        if (priorityResult != null) {
            return@withContext priorityResult
        }

        // 3. Scan remaining subnet addresses in parallel chunks
        val remainingIps = mutableListOf<String>()
        val testedSet = priorityIps.toSet()
        for (prefix in prefixes) {
            for (i in 1..254) {
                val ip = "$prefix.$i"
                if (!testedSet.contains(ip)) {
                    remainingIps.add(ip)
                }
            }
        }

        // Probe in parallel batches of 32 concurrent requests
        val chunkSize = 32
        for (i in remainingIps.indices step chunkSize) {
            val chunk = remainingIps.subList(i, minOf(i + chunkSize, remainingIps.size))
            val result = probeBatchInParallel(chunk, DEFAULT_PORT, 650)
            if (result != null) {
                return@withContext result
            }
        }

        null
    }

    /**
     * Probe a batch of IPs concurrently and return the first responding CapsStream endpoint.
     */
    private suspend fun probeBatchInParallel(ips: List<String>, port: Int, timeoutMs: Int): String? = withContext(Dispatchers.IO) {
        val jobs = ips.map { ip ->
            async {
                if (isCapsStreamServer(ip, port, timeoutMs)) {
                    "http://$ip:$port"
                } else {
                    null
                }
            }
        }
        val results = jobs.awaitAll()
        results.firstOrNull { it != null }
    }

    /**
     * Checks whether an endpoint is a live CapsStream instance by querying /api/health.
     */
    suspend fun isCapsStreamServer(ip: String, port: Int, timeoutMs: Int = PROBE_TIMEOUT_MS): Boolean = withContext(Dispatchers.IO) {
        try {
            val endpoint = URL("http://$ip:$port/api/health")
            val conn = (endpoint.openConnection() as HttpURLConnection).apply {
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                requestMethod = "GET"
                setRequestProperty("User-Agent", "CapsStream-AndroidTV")
            }
            conn.connect()
            val code = conn.responseCode
            conn.disconnect()
            code in 200..399
        } catch (e: Exception) {
            false
        }
    }

    /**
     * Broadcasts a UDP discovery packet on local network and waits for CapsStream server response.
     */
    private suspend fun probeUdpBroadcast(): String? = withContext(Dispatchers.IO) {
        var socket: DatagramSocket? = null
        try {
            socket = DatagramSocket().apply {
                broadcast = true
                soTimeout = 600
            }
            val msg = "CAPSSTREAM_DISCOVER".toByteArray()
            val packet = DatagramPacket(msg, msg.size, InetAddress.getByName("255.255.255.255"), UDP_DISCOVERY_PORT)
            socket.send(packet)

            val buffer = ByteArray(1024)
            val responsePacket = DatagramPacket(buffer, buffer.size)
            socket.receive(responsePacket)

            val text = String(responsePacket.data, 0, responsePacket.length)
            val json = JSONObject(text)
            if (json.optString("service") == "capsstream") {
                val ip = json.optString("ip")
                val port = json.optInt("port", DEFAULT_PORT)
                val url = json.optString("url")
                if (url.isNotEmpty()) {
                    return@withContext url
                } else if (ip.isNotEmpty()) {
                    return@withContext "http://$ip:$port"
                }
            }
        } catch (e: Exception) {
            // UDP broadcast not supported or timed out — fallback to subnet probe
        } finally {
            socket?.close()
        }
        null
    }

    /**
     * Collects all genuine IPv4 subnet prefixes, filtering out Wi-Fi Direct (p2p), VPNs, and dummy interfaces.
     */
    private fun getSubnetPrefixes(context: Context): List<String> {
        val prefixes = mutableSetOf<String>()
        try {
            val interfaces = java.net.NetworkInterface.getNetworkInterfaces()
            if (interfaces != null) {
                for (intf in interfaces.asSequence()) {
                    if (intf.isLoopback || !intf.isUp) continue
                    val name = intf.name.lowercase()
                    // Filter out Wi-Fi Direct, cell tethering, and VPN interfaces
                    if (name.startsWith("p2p") || name.startsWith("dummy") || name.startsWith("tun") || name.startsWith("tap")) {
                        continue
                    }
                    for (addr in intf.inetAddresses.asSequence()) {
                        if (!addr.isLoopbackAddress && addr is java.net.Inet4Address) {
                            val host = addr.hostAddress ?: continue
                            val parts = host.split(".")
                            if (parts.size == 4 && parts[0] != "127") {
                                prefixes.add("${parts[0]}.${parts[1]}.${parts[2]}")
                            }
                        }
                    }
                }
            }
        } catch (e: Exception) {
            // Ignore interface iteration errors
        }

        // Also check WifiManager connection
        try {
            val wm = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            val ipInt = wm?.connectionInfo?.ipAddress ?: 0
            if (ipInt != 0) {
                val ip = InetAddress.getByAddress(
                    byteArrayOf(
                        (ipInt and 0xff).toByte(),
                        (ipInt shr 8 and 0xff).toByte(),
                        (ipInt shr 16 and 0xff).toByte(),
                        (ipInt shr 24 and 0xff).toByte()
                    )
                ).hostAddress
                if (ip != null) {
                    val parts = ip.split(".")
                    if (parts.size == 4 && parts[0] != "127") {
                        prefixes.add("${parts[0]}.${parts[1]}.${parts[2]}")
                    }
                }
            }
        } catch (e: Exception) {
            // Ignore WifiManager errors
        }

        if (prefixes.isEmpty()) {
            prefixes.add("192.168.1")
        }
        return prefixes.toList()
    }
}
