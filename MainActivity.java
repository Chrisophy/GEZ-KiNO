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

        // Vollbildmodus aktivieren
        hideSystemUI();

        WebView webView = new WebView(this);
        WebSettings webSettings = webView.getSettings();
        
        webSettings.setJavaScriptEnabled(true);
        webSettings.setDomStorageEnabled(true);
        
        webView.setWebViewClient(new WebViewClient());
        
        // HIER die gewünschte URL eintragen:
        webView.loadUrl("https://chrisophy.github.io/GEZ-KiNO");
        
        setContentView(webView);
    }

    private void hideSystemUI() {
        // 1. App-Titelzeile ausblenden (falls im Theme vorhanden)
        if (getSupportActionBar() != null) {
            getSupportActionBar().hide();
        }

        // 2. Status- und Navigationsleiste ausblenden
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        WindowInsetsControllerCompat controller = new WindowInsetsControllerCompat(getWindow(), getWindow().getDecorView());
        
        // Versteckt Statusbar und Navigationbar
        controller.hide(WindowInsetsCompat.Type.statusBars() | WindowInsetsCompat.Type.navigationBars());
        
        // Reagiert auf Wischgesten: Leisten werden bei Wischen kurz halbtransparent eingeblendet und verschwinden automatisch wieder
        controller.setSystemBarsBehavior(WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
    }
}
