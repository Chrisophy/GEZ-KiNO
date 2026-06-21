package com.template.htmlwrapper;

import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WebView webView = new WebView(this);
        WebSettings webSettings = webView.getSettings();
        
        // FIX: "set" statt "get" verwenden!
        webSettings.setJavaScriptEnabled(true); // Wichtig für modernes HTML/JS
        webSettings.setDomStorageEnabled(true);
        
        webView.setWebViewClient(new WebViewClient());
        
        // HIER die gewünschte URL eintragen:
        webView.loadUrl("https://tele5.de");
        
        setContentView(webView);
    }
}
