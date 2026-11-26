#!/usr/bin/env python3
"""
Patches Godot's unpacked android/build Gradle project to integrate:
- firebase/google-services.json
- Google Services Gradle plugin + Firebase BoM (Auth, Firestore, Analytics) + Play Services Auth
- MiniRallyAuthPlugin.java (Godot v2 Android plugin for optional Google Sign-In & Firestore Leaderboard)
"""
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANDROID_BUILD = ROOT / "android" / "build"
GOOGLE_SERVICES_SRC = ROOT / "firebase" / "google-services.json"
PLUGIN_JAVA_SRC = ROOT / "firebase" / "java" / "MiniRallyAuthPlugin.java"


def patch_build_gradle(gradle_path: Path) -> None:
    text = gradle_path.read_text(encoding="utf-8")

    # 1. Apply com.google.gms.google-services plugin (supports both plugins {} DSL and buildscript {})
    if "com.google.gms" not in text:
        if re.search(r"^\s*plugins\s*\{", text, re.MULTILINE):
            text, count = re.subn(
                r"(^\s*plugins\s*\{)",
                r"\1\n    id 'com.google.gms.google-services' version '4.4.2'",
                text,
                count=1,
                flags=re.MULTILINE,
            )
            if count == 0:
                raise RuntimeError("Failed to inject google-services into plugins block")
        elif re.search(r"buildscript\s*\{[\s\S]*?dependencies\s*\{", text):
            text = re.sub(
                r"(buildscript\s*\{[\s\S]*?dependencies\s*\{)",
                r"\1\n        classpath 'com.google.gms:google-services:4.4.2'",
                text,
                count=1,
            )
            text = text.rstrip() + "\n\napply plugin: 'com.google.gms.google-services'\n"
        else:
            header = (
                "buildscript {\n"
                "    repositories {\n"
                "        google()\n"
                "        mavenCentral()\n"
                "    }\n"
                "    dependencies {\n"
                "        classpath 'com.google.gms:google-services:4.4.2'\n"
                "    }\n"
                "}\n\n"
            )
            text = header + text.rstrip() + "\n\napply plugin: 'com.google.gms.google-services'\n"

    # 2. Add Firebase + Google Sign-In dependencies inside top-level dependencies { ... }
    if "com.google.firebase:firebase-auth" not in text:
        firebase_deps = (
            "\n    implementation platform('com.google.firebase:firebase-bom:33.7.0')\n"
            "    implementation 'com.google.firebase:firebase-analytics'\n"
            "    implementation 'com.google.firebase:firebase-auth'\n"
            "    implementation 'com.google.firebase:firebase-firestore'\n"
            "    implementation 'com.google.android.gms:play-services-auth:21.3.0'\n"
        )
        # Find top-level dependencies { (at start of line, not indented inside buildscript)
        deps_match = re.search(r"^dependencies\s*\{", text, re.MULTILINE)
        if deps_match:
            insert_pos = deps_match.end()
            text = text[:insert_pos] + firebase_deps + text[insert_pos:]
        else:
            text = text.rstrip() + "\n\ndependencies {" + firebase_deps + "}\n"

    gradle_path.write_text(text, encoding="utf-8")
    print(f"[setup_firebase_android] Patched {gradle_path}")


def patch_manifest(manifest_path: Path) -> None:
    text = manifest_path.read_text(encoding="utf-8")
    meta_name = "org.godotengine.plugin.v2.MiniRallyAuth"
    if meta_name not in text:
        meta_tag = (
            '        <meta-data\n'
            '            android:name="org.godotengine.plugin.v2.MiniRallyAuth"\n'
            '            android:value="com.cynorra.apexminirally.MiniRallyAuthPlugin" />\n'
            '    </application>'
        )
        if "</application>" not in text:
            raise RuntimeError("Could not find </application> in AndroidManifest.xml")
        text = text.replace("</application>", meta_tag, 1)
        manifest_path.write_text(text, encoding="utf-8")
        print(f"[setup_firebase_android] Registered MiniRallyAuth plugin in {manifest_path}")


def main() -> int:
    if not ANDROID_BUILD.exists():
        print(f"ERROR: {ANDROID_BUILD} does not exist", file=sys.stderr)
        return 1
    if not GOOGLE_SERVICES_SRC.exists():
        print(f"ERROR: {GOOGLE_SERVICES_SRC} does not exist", file=sys.stderr)
        return 1
    if not PLUGIN_JAVA_SRC.exists():
        print(f"ERROR: {PLUGIN_JAVA_SRC} does not exist", file=sys.stderr)
        return 1

    # Copy google-services.json
    shutil.copy2(GOOGLE_SERVICES_SRC, ANDROID_BUILD / "google-services.json")
    print(f"[setup_firebase_android] Copied google-services.json -> {ANDROID_BUILD / 'google-services.json'}")

    # Copy MiniRallyAuthPlugin.java
    java_dst_dir = ANDROID_BUILD / "src" / "com" / "cynorra" / "apexminirally"
    java_dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PLUGIN_JAVA_SRC, java_dst_dir / "MiniRallyAuthPlugin.java")
    print(f"[setup_firebase_android] Copied MiniRallyAuthPlugin.java -> {java_dst_dir}")

    # Patch build.gradle and AndroidManifest.xml
    patch_build_gradle(ANDROID_BUILD / "build.gradle")
    patch_manifest(ANDROID_BUILD / "AndroidManifest.xml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
