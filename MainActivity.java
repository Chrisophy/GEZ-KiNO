package com.template.htmlwrapper;

import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;

public class MainActivity extends AppCompatActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Statusleiste ausblenden (Vollbildmodus)
        WindowInsetsControllerCompat controller = 
                WindowCompat.getInsetsController(getWindow(), getWindow().getDecorView());
        if (controller != null) {
            // Blendet die Statusleiste oben aus
            controller.hide(WindowInsetsCompat.Type.statusBars());
            
            // Optional: Zeigt die Leiste kurz an, wenn man vom oberen Rand nach unten wischt
            controller.setSystemBarsBehavior(
                    WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            );
        }

        WebView webView = new WebView(this);
        WebSettings webSettings = webView.getSettings();
        
        webSettings.setJavaScriptEnabled(true);
        webSettings.setDomStorageEnabled(true);
        
        webView.setWebViewClient(new WebViewClient());
        
        webView.loadUrl("https://chrisophy.github.io/GEZ-KiNO");
        
        setContentView(webView);
    }
}
