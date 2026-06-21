import os
import shutil
import re

def setup_apk_project(app_name, package_name, html_source_dir, template_dir="template"):
    build_dir = "build_output"
    
    # 1. Template kopieren
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    shutil.copytree(template_dir, build_dir)
    
    # 2. HTML-Dateien in den Assets-Ordner schieben
    assets_dir = os.path.join(build_dir, "app", "src", "main", "assets")
    os.makedirs(assets_dir, exist_ok=True)
    shutil.copytree(html_source_dir, assets_dir, dirs_exist_ok=True)
    
    # 3. Paketnamen in der build.gradle anpassen
    gradle_path = os.path.join(build_dir, "app", "build.gradle")
    with open(gradle_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r'applicationId ".*?"', f'applicationId "{package_name}"', content)
    with open(gradle_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    # 4. App-Namen in strings.xml anpassen
    strings_path = os.path.join(build_dir, "app", "src", "main", "res", "values", "strings.xml")
    with open(strings_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r'<string name="app_name">.*?</string>', f'<string name="app_name">{app_name}</string>', content)
    with open(strings_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Projekt für '{app_name}' vorbereitet. Starte Gradle Build...")
    
    # 5. Gradle Build triggern
    os.chdir(build_dir)
    os.system("./gradlew assembleDebug") # Oder assembleRelease für die finale Version

if __name__ == "__main__":
    setup_apk_project(
        app_name="[GEZ] KiNO",
        package_name="gez.index.kino",
        html_source_dir="./"
    )
