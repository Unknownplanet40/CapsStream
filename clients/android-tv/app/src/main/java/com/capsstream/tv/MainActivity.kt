package com.capsstream.tv

import android.annotation.SuppressLint
import android.content.Context
import android.os.Bundle
import android.view.KeyEvent
import android.view.View
import android.webkit.*
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var discoveryOverlay: LinearLayout
    private lateinit var progressBar: ProgressBar
    private lateinit var statusText: TextView
    private lateinit var manualConnectLayout: LinearLayout
    private lateinit var ipEditText: EditText
    private lateinit var btnConnect: Button
    private lateinit var btnRetry: Button

    private var serverUrl: String? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        discoveryOverlay = findViewById(R.id.discoveryOverlay)
        progressBar = findViewById(R.id.progressBar)
        statusText = findViewById(R.id.statusText)
        manualConnectLayout = findViewById(R.id.manualConnectLayout)
        ipEditText = findViewById(R.id.ipEditText)
        btnConnect = findViewById(R.id.btnConnect)
        btnRetry = findViewById(R.id.btnRetry)

        setupWebView()
        setupListeners()

        val prefs = getSharedPreferences("capsstream_tv", Context.MODE_PRIVATE)
        val savedUrl = prefs.getString("last_server_url", null)

        if (!savedUrl.isNullOrBlank()) {
            connectToServer(savedUrl)
        } else {
            startDiscovery()
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.mediaPlaybackRequiresUserGesture = false
        settings.allowFileAccess = false
        settings.databaseEnabled = true
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW

        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)

        webView.webChromeClient = object : WebChromeClient() {}
        webView.webViewClient = object : WebViewClient() {
            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                super.onReceivedError(view, request, error)
                if (request?.isForMainFrame == true) {
                    showManualConnect("Could not connect to CapsStream. Please check IP and port.")
                }
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                // Automatically activate TV layout mode when running inside this app.
                // This mirrors what setLayoutMode("tv") does in app.js:
                //   1. Persist the preference so it survives page reloads.
                //   2. Update the reactive store so Vue components re-render immediately.
                //   3. Add the CSS class so layout-tv-mode styles apply right away.
                view?.evaluateJavascript("""
                    (function() {
                        try {
                            localStorage.setItem('capsstream_layout_mode', 'tv');
                            if (window.store && window.store.layoutMode !== 'tv') {
                                window.store.layoutMode = 'tv';
                                document.body.classList.add('layout-tv-mode');
                            } else if (!window.store) {
                                document.body.classList.add('layout-tv-mode');
                            }
                        } catch(e) {}
                    })();
                """.trimIndent(), null)
            }
        }
    }

    private fun setupListeners() {
        btnConnect.setOnClickListener {
            val input = ipEditText.text.toString().trim()
            if (input.isNotEmpty()) {
                var formatted = if (input.startsWith("http://") || input.startsWith("https://")) {
                    input
                } else {
                    "http://$input"
                }
                // If user didn't specify a port (e.g. 192.168.1.5), default to :8000
                val hostPart = formatted.substringAfter("://").substringBefore("/")
                if (!hostPart.contains(":")) {
                    formatted = if (formatted.contains("/")) {
                        val scheme = formatted.substringBefore("://")
                        val path = formatted.substringAfter("://").substringAfter("/")
                        "$scheme://$hostPart:8000/$path"
                    } else {
                        "$formatted:8000"
                    }
                }
                connectToServer(formatted)
            }
        }

        btnRetry.setOnClickListener {
            startDiscovery()
        }
    }

    private fun startDiscovery() {
        discoveryOverlay.visibility = View.VISIBLE
        progressBar.visibility = View.VISIBLE
        manualConnectLayout.visibility = View.VISIBLE
        statusText.text = getString(R.string.server_discovery)

        lifecycleScope.launch {
            val discovered = DiscoveryHelper.discoverServer(this@MainActivity)
            if (discovered != null) {
                connectToServer(discovered)
            } else {
                progressBar.visibility = View.GONE
                statusText.text = getString(R.string.server_not_found)
            }
        }
    }

    private fun connectToServer(url: String) {
        serverUrl = url
        val prefs = getSharedPreferences("capsstream_tv", Context.MODE_PRIVATE)
        prefs.edit().putString("last_server_url", url).apply()

        statusText.text = getString(R.string.server_connecting)
        progressBar.visibility = View.VISIBLE
        manualConnectLayout.visibility = View.GONE

        webView.visibility = View.VISIBLE
        discoveryOverlay.visibility = View.GONE
        webView.loadUrl(url)
        webView.requestFocus()
    }

    private fun showManualConnect(msg: String) {
        webView.visibility = View.GONE
        discoveryOverlay.visibility = View.VISIBLE
        progressBar.visibility = View.GONE
        manualConnectLayout.visibility = View.VISIBLE
        statusText.text = msg
        ipEditText.requestFocus()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (webView.visibility == View.VISIBLE) {
            when (keyCode) {
                KeyEvent.KEYCODE_BACK -> {
                    if (webView.canGoBack()) {
                        webView.goBack()
                        return true
                    } else {
                        showManualConnect("Disconnected from server.")
                        return true
                    }
                }
                KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
                KeyEvent.KEYCODE_MEDIA_PLAY,
                KeyEvent.KEYCODE_MEDIA_PAUSE -> {
                    // Dispatch space bar key event to trigger video play/pause
                    webView.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_SPACE))
                    webView.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_SPACE))
                    return true
                }
            }
        }
        return super.onKeyDown(keyCode, event)
    }
}
