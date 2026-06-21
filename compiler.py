import os
import shutil
import subprocess

def create_android_boilerplate(build_dir, app_name, package_name, start_url):
    """Generiert eine saubere Android-Projektstruktur mit Fullscreen- und Download-Support."""
    package_path = package_name.replace(".", "/")
    java_dir = os.path.join(build_dir, "app", "src", "main", "java", package_path)
    res_val_dir = os.path.join(build_dir, "app", "src", "main", "res", "values")
    res_mipmap_dir = os.path.join(build_dir, "app", "src", "main", "res", "mipmap")
    
    os.makedirs(java_dir, exist_ok=True)
    os.makedirs(res_val_dir, exist_ok=True)
    os.makedirs(res_mipmap_dir, exist_ok=True)
    
    # 1. settings.gradle
    settings_gradle = """
    pluginManagement {
        repositories {
            google()
            mavenCentral()
            gradlePluginPortal()
        }
    }
    dependencyResolutionManagement {
        repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
        repositories {
            google()
            mavenCentral()
        }
    }
    rootProject.name = "HTMLWrapperApp"
    include ':app'
    """
    with open(os.path.join(build_dir, "settings.gradle"), "w", encoding="utf-8") as f:
        f.write(settings_gradle.strip())
        
    # 2. Root build.gradle
    root_gradle = """
    plugins {
        id 'com.android.application' version '8.1.4' apply false
    }
    """
    with open(os.path.join(build_dir, "build.gradle"), "w", encoding="utf-8") as f:
        f.write(root_gradle.strip())

    # 2b. gradle.properties
    gradle_properties = """
    android.useAndroidX=true
    """
    with open(os.path.join(build_dir, "gradle.properties"), "w", encoding="utf-8") as f:
        f.write(gradle_properties.strip())
        
    # 3. app/build.gradle
    app_gradle = f"""
    plugins {{
        id 'com.android.application'
    }}
    android {{
        namespace "{package_name}"
        compileSdk 34
        defaultConfig {{
            applicationId "{package_name}"
            minSdk 21
            targetSdk 34
            versionCode 1
            versionName "1.0"
        }}
        buildTypes {{
            release {{
                minifyEnabled false
            }}
        }}
    }}
    dependencies {{
        implementation 'androidx.appcompat:appcompat:1.6.1'
    }}
    """
    with open(os.path.join(build_dir, "app", "build.gradle"), "w", encoding="utf-8") as f:
        f.write(app_gradle.strip())
        
    # 4. AndroidManifest.xml (Speicher-Berechtigung für ältere APIs hinzugefügt)
    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
    <manifest xmlns:android="http://schemas.android.com/apk/res/android"
        package="{package_name}">
        <uses-permission android:name="android.permission.INTERNET" />
        <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="28" />
        <application
            android:allowBackup="true"
            android:icon="@mipmap/ic_launcher"
            android:label="@string/app_name"
            android:theme="@style/Theme.AppCompat.Light.NoActionBar">
            <activity android:name=".MainActivity" 
                android:exported="true"
                android:configChanges="orientation|screenSize|keyboardHidden|screenLayout">
                <intent-filter>
                    <action android:name="android.intent.action.MAIN" />
                    <category android:name="android.intent.category.LAUNCHER" />
                </intent-filter>
            </activity>
        </application>
    </manifest>
    """
    with open(os.path.join(build_dir, "app", "src", "main", "AndroidManifest.xml"), "w", encoding="utf-8") as f:
        f.write(manifest.strip())
        
    # 5. strings.xml
    strings = f"""<?xml version="1.0" encoding="utf-8"?>
    <resources>
        <string name="app_name">{app_name}</string>
    </resources>
    """
    with open(os.path.join(res_val_dir, "strings.xml"), "w", encoding="utf-8") as f:
        f.write(strings.strip())
        
    # 6. MainActivity.java (DownloadListener implementiert!)
    main_activity = f"""package {package_name};

    import android.app.DownloadManager;
    import android.net.Uri;
    import android.os.Bundle;
    import android.os.Environment;
    import android.view.View;
    import android.view.ViewGroup;
    import android.webkit.CookieManager;
    import android.webkit.DownloadListener;
    import android.webkit.URLUtil;
    import android.webkit.WebChromeClient;
    import android.webkit.WebSettings;
    import android.webkit.WebView;
    import android.webkit.WebViewClient;
    import android.widget.FrameLayout;
    import android.widget.Toast;
    import androidx.appcompat.app.AppCompatActivity;

    public class MainActivity extends AppCompatActivity {{
        private WebView webView;
        private FrameLayout customViewContainer;
        private View customView;
        private WebChromeClient.CustomViewCallback customViewCallback;

        @Override
        protected void onCreate(Bundle savedInstanceState) {{
            super.onCreate(savedInstanceState);
            
            FrameLayout mainLayout = new FrameLayout(this);
            
            webView = new WebView(this);
            WebSettings webSettings = webView.getSettings();
            webSettings.setJavaScriptEnabled(true);
            webSettings.setDomStorageEnabled(true);
            webSettings.setDatabaseEnabled(true);
            
            customViewContainer = new FrameLayout(this);
            customViewContainer.setVisibility(View.GONE);
            
            mainLayout.addView(webView, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            mainLayout.addView(customViewContainer, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            
            setContentView(mainLayout);
            
            webView.setWebViewClient(new WebViewClient());
            
            // Vollbild-Support
            webView.setWebChromeClient(new WebChromeClient() {{
                @Override
                public void onShowCustomView(View view, CustomViewCallback callback) {{
                    if (customView != null) {{
                        onHideCustomView();
                        return;
                    }}
                    customView = view;
                    customViewContainer.addView(customView, new FrameLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
                    customViewContainer.setVisibility(View.VISIBLE);
                    customViewCallback = callback;
                    
                    getWindow().getDecorView().setSystemUiVisibility(
                            View.SYSTEM_UI_FLAG_FULLSCREEN |
                            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    );
                }}

                @Override
                public void onHideCustomView() {{
                    if (customView == null) return;
                    customViewContainer.removeView(customView);
                    customViewContainer.setVisibility(View.GONE);
                    customView = null;
                    if (customViewCallback != null) {{
                        customViewCallback.onCustomViewHidden();
                    }}
                    getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
                }}
            }});

            // HIER NEU: Download-Handling über den Android DownloadManager
            webView.setDownloadListener(new DownloadListener() {{
                @Override
                public void onDownloadStart(String url, String userAgent, String contentDisposition, String mimetype, long contentLength) {{
                    try {{
                        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                        request.setMimeType(mimetype);
                        
                        // Cookies mitgeben, falls die Session geschützt ist
                        String cookies = CookieManager.getInstance().getCookie(url);
                        request.addRequestHeader("cookie", cookies);
                        request.addRequestHeader("User-Agent", userAgent);
                        
                        // Titel der Datei erraten & Notification einrichten
                        String filename = URLUtil.guessFileName(url, contentDisposition, mimetype);
                        request.setTitle(filename);
                        request.setDescription("Datei wird heruntergeladen...");
                        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                        
                        // Ziel: Öffentlicher "Download"-Ordner auf dem Gerät
                        request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename);
                        
                        DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
                        if (dm != null) {{
                            dm.enqueue(request);
                            Toast.makeText(getApplicationContext(), "Download gestartet: " + filename, Toast.LENGTH_LONG).show();
                        }}
                    }} catch (Exception e) {{
                        Toast.makeText(getApplicationContext(), "Fehler beim Download: " + e.getMessage(), Toast.LENGTH_LONG).show();
                    }}
                }}
            }});
            
            webView.loadUrl("{start_url}");
        }}

        @Override
        public void onBackPressed() {{
            if (customView != null) {{
                if (webView.getWebChromeClient() != null) {{
                    webView.getWebChromeClient().onHideCustomView();
                }}
            }} else if (webView.canGoBack()) {{
                webView.goBack();
            }} else {{
                super.onBackPressed();
            }}
        }}
    }}
    """
    with open(os.path.join(java_dir, "MainActivity.java"), "w", encoding="utf-8") as f:
        f.write(main_activity.strip())


def build_apk(app_name, package_name, start_url, html_source_dir=None):
    build_dir = "build_output"
    
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
        
    print("-> Erstelle Android-Projektstruktur...")
    create_android_boilerplate(build_dir, app_name, package_name, start_url)
    
    if html_source_dir and os.path.exists(html_source_dir) and start_url.startswith("file:///"):
        print("-> Kopiere HTML-Dateien in die App-Assets...")
        assets_dir = os.path.join(build_dir, "app", "src", "main", "assets")
        
        def ignore_folders(src, names):
            return ['build_output', '.git', '.github', 'compiler.py', 'icon.png']
            
        shutil.copytree(html_source_dir, assets_dir, dirs_exist_ok=True, ignore=ignore_folders)
    
    if html_source_dir and os.path.exists(html_source_dir):
        icon_source = os.path.join(html_source_dir, "icon.png")
        if os.path.exists(icon_source):
            print("-> App-Icon gefunden und wird ins Projekt integriert...")
            target_icon_path = os.path.join(build_dir, "app", "src", "main", "res", "mipmap", "ic_launcher.png")
            shutil.copy(icon_source, target_icon_path)
        else:
            print("-> HINWEIS: Keine 'icon.png' gefunden. Standard-Icon wird verwendet.")
            
    print("-> Starte Gradle Buildprozess...")
    
    try:
        subprocess.run(["gradle", "assembleDebug"], cwd=build_dir, check=True)
        print("-> Build erfolgreich beendet!")
    except subprocess.CalledProcessError as e:
        print(f"-> FEHLER: Gradle-Build ist mit Code {e.returncode} fehlgeschlagen.")
        exit(1)


if __name__ == "__main__":
    build_apk(
        app_name="[GEZ] KiNO",
        package_name="gez.kino.world",
        start_url="https://chrisophy.github.io/GEZ-KiNO",
        html_source_dir="./pagina"
    )
