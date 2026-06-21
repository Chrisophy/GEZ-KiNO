import os
import shutil

def create_android_boilerplate(build_dir, app_name, package_name):
    """Generiert alle notwendigen Android-Projektdateien aus dem Nichts."""
    # Verzeichnisstruktur anlegen
    package_path = package_name.replace(".", "/")
    java_dir = os.path.join(build_dir, "app", "src", "main", "java", package_path)
    res_val_dir = os.path.join(build_dir, "app", "src", "main", "res", "values")
    
    os.makedirs(java_dir, exist_ok=True)
    os.makedirs(res_val_dir, exist_ok=True)
    
    # 1. settings.gradle
    with open(os.path.join(build_dir, "settings.gradle"), "w", encoding="utf-8") as f:
        f.write("include ':app'\n")
        
    # 2. Root build.gradle
    root_gradle = """
    buildscript {
        repositories { google() \n mavenCentral() }
        dependencies { classpath 'com.android.tools.build:gradle:8.1.4' }
    }
    allprojects {
        repositories { google() \n mavenCentral() }
    }
    """
    with open(os.path.join(build_dir, "build.gradle"), "w", encoding="utf-8") as f:
        f.write(root_gradle)
        
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
        f.write(app_gradle)
        
    # 4. AndroidManifest.xml
    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
    <manifest xmlns:android="http://schemas.github.com/apk/res/android">
        <uses-permission android:name="android.permission.INTERNET" />
        <application
            android:allowBackup="true"
            android:label="@string/app_name"
            android:theme="@style/Theme.AppCompat.Light.NoActionBar">
            <activity android:name=".MainActivity" android:exported="true">
                <intent-filter>
                    <action android:name="android.intent.action.MAIN" />
                    <category android:name="android.intent.category.LAUNCHER" />
                </intent-filter>
            </activity>
        </application>
    </manifest>
    """
    with open(os.path.join(build_dir, "app", "src", "main", "AndroidManifest.xml"), "w", encoding="utf-8") as f:
        f.write(manifest)
        
    # 5. strings.xml (App-Name)
    strings = f"""<?xml version="1.0" encoding="utf-8"?>
    <resources>
        <string name="app_name">{app_name}</string>
    </resources>
    """
    with open(os.path.join(res_val_dir, "strings.xml"), "w", encoding="utf-8") as f:
        f.write(strings)
        
    # 6. MainActivity.java (Die native Fullscreen-WebView)
    main_activity = f"""package {package_name};

    import android.os.Bundle;
    import android.webkit.WebSettings;
    import android.webkit.WebView;
    import android.webkit.WebViewClient;
    import androidx.appcompat.app.AppCompatActivity;

    public class MainActivity extends AppCompatActivity {{
        @Override
        protected void onCreate(Bundle savedInstanceState) {{
            super.onCreate(savedInstanceState);
            WebView webView = new WebView(this);
            WebSettings webSettings = webView.getSettings();
            webSettings.setJavaScriptEnabled(true);
            webSettings.setDomStorageEnabled(true);
            webSettings.setDatabaseEnabled(true);
            
            webView.setWebViewClient(new WebViewClient());
            webView.loadUrl("file:///android_asset/index.html");
            setContentView(webView);
        }}
    }}
    """
    with open(os.path.join(java_dir, "MainActivity.java"), "w", encoding="utf-8") as f:
        f.write(main_activity)


def build_apk(app_name, package_name, html_source_dir):
    build_dir = "build_output"
    
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
        
    print("-> Erstelle Android-Projektstruktur...")
    create_android_boilerplate(build_dir, app_name, package_name)
    
    print("-> Kopiere HTML-Dateien in die App-Assets...")
    assets_dir = os.path.join(build_dir, "app", "src", "main", "assets")
    
    # Ignoriere Build-Ordner und Git-Dateien, um Endlosschleifen zu verhindern
    def ignore_folders(src, names):
        return ['build_output', '.git', '.github', 'compiler.py']
        
    shutil.copytree(html_source_dir, assets_dir, dirs_exist_ok=True, ignore=ignore_folders)
    
    print("-> Starte Gradle Buildprozess...")
    os.chdir(build_dir)
    # Wir rufen direkt das globale 'gradle' auf, das GitHub bereitstellt
    os.system("gradle assembleDebug")


if __name__ == "__main__":
    build_apk(
        app_name="[GEZ] KiNO",
        package_name="gez.index.kino",
        html_source_dir="./"
    )
