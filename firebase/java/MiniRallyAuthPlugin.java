package com.cynorra.apexminirally;

import android.app.Activity;
import android.content.Intent;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.android.gms.auth.api.signin.GoogleSignIn;
import com.google.android.gms.auth.api.signin.GoogleSignInAccount;
import com.google.android.gms.auth.api.signin.GoogleSignInClient;
import com.google.android.gms.auth.api.signin.GoogleSignInOptions;
import com.google.android.gms.common.api.ApiException;
import com.google.android.gms.tasks.Task;
import com.google.firebase.auth.AuthCredential;
import com.google.firebase.auth.FirebaseAuth;
import com.google.firebase.auth.FirebaseUser;
import com.google.firebase.auth.GoogleAuthProvider;
import com.google.firebase.firestore.DocumentReference;
import com.google.firebase.firestore.DocumentSnapshot;
import com.google.firebase.firestore.FieldValue;
import com.google.firebase.firestore.FirebaseFirestore;
import com.google.firebase.firestore.Query;
import com.google.firebase.firestore.QueryDocumentSnapshot;

import org.godotengine.godot.Godot;
import org.godotengine.godot.plugin.GodotPlugin;
import org.godotengine.godot.plugin.SignalInfo;
import org.godotengine.godot.plugin.UsedByGodot;
import org.json.JSONArray;
import org.json.JSONObject;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

public class MiniRallyAuthPlugin extends GodotPlugin {
    private static final String TAG = "MiniRallyAuth";
    private static final int RC_SIGN_IN = 9412;

    private static final String[] ALL_TRACKS = new String[] {
            "pine_loop", "tent_town", "zigzag", "lakeside", "canyon",
            "esses", "hairpin", "chicane", "twin", "grand",
            "desert_speedway", "neon_velocity", "apex_summit"
    };

    private FirebaseAuth auth;
    private FirebaseFirestore db;

    public MiniRallyAuthPlugin(Godot godot) {
        super(godot);
        try {
            auth = FirebaseAuth.getInstance();
            db = FirebaseFirestore.getInstance();
        } catch (Exception e) {
            Log.e(TAG, "Firebase init error: " + e.getMessage());
        }
    }

    @NonNull
    @Override
    public String getPluginName() {
        return "MiniRallyAuth";
    }

    @NonNull
    @Override
    public Set<SignalInfo> getPluginSignals() {
        Set<SignalInfo> signals = new HashSet<>();
        signals.add(new SignalInfo("signed_in", String.class, String.class, String.class));
        signals.add(new SignalInfo("sign_in_failed", String.class));
        signals.add(new SignalInfo("signed_out"));
        signals.add(new SignalInfo("account_deleted"));
        signals.add(new SignalInfo("delete_failed", String.class));
        signals.add(new SignalInfo("leaderboard_loaded", String.class, String.class));
        signals.add(new SignalInfo("score_submitted", String.class, Boolean.class));
        return signals;
    }

    private GoogleSignInClient buildGoogleClient(Activity activity) {
        int resId = activity.getResources().getIdentifier(
                "default_web_client_id", "string", activity.getPackageName());
        String webClientId = resId != 0 ? activity.getString(resId) : "";
        GoogleSignInOptions.Builder builder = new GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN)
                .requestEmail();
        if (webClientId != null && !webClientId.isEmpty()) {
            builder.requestIdToken(webClientId);
        }
        return GoogleSignIn.getClient(activity, builder.build());
    }

    @UsedByGodot
    public String get_current_user() {
        try {
            JSONObject obj = new JSONObject();
            FirebaseUser user = auth != null ? auth.getCurrentUser() : null;
            if (user != null) {
                obj.put("signed_in", true);
                obj.put("uid", user.getUid());
                obj.put("name", user.getDisplayName() != null ? user.getDisplayName() : "Racer");
                obj.put("email", user.getEmail() != null ? user.getEmail() : "");
            } else {
                obj.put("signed_in", false);
            }
            return obj.toString();
        } catch (Exception e) {
            return "{\"signed_in\":false}";
        }
    }

    @UsedByGodot
    public void sign_in_google() {
        Activity activity = getActivity();
        if (activity == null || auth == null) {
            emitSignal("sign_in_failed", "Auth unavailable");
            return;
        }
        int resId = activity.getResources().getIdentifier(
                "default_web_client_id", "string", activity.getPackageName());
        if (resId == 0 || activity.getString(resId).isEmpty()) {
            emitSignal("sign_in_failed", "Google Sign-In not configured in Firebase yet");
            return;
        }
        activity.runOnUiThread(() -> {
            try {
                GoogleSignInClient client = buildGoogleClient(activity);
                Intent signInIntent = client.getSignInIntent();
                activity.startActivityForResult(signInIntent, RC_SIGN_IN);
            } catch (Exception e) {
                emitSignal("sign_in_failed", e.getMessage() != null ? e.getMessage() : "Sign-in launch failed");
            }
        });
    }

    @Override
    public void onMainActivityResult(int requestCode, int resultCode, @Nullable Intent data) {
        if (requestCode != RC_SIGN_IN) {
            return;
        }
        Task<GoogleSignInAccount> task = GoogleSignIn.getSignedInAccountFromIntent(data);
        try {
            GoogleSignInAccount account = task.getResult(ApiException.class);
            if (account == null || account.getIdToken() == null) {
                emitSignal("sign_in_failed", "Missing Google ID token");
                return;
            }
            AuthCredential credential = GoogleAuthProvider.getCredential(account.getIdToken(), null);
            auth.signInWithCredential(credential).addOnCompleteListener(authTask -> {
                if (authTask.isSuccessful() && auth.getCurrentUser() != null) {
                    FirebaseUser user = auth.getCurrentUser();
                    String uid = user.getUid();
                    String name = user.getDisplayName() != null ? user.getDisplayName() : "Racer";
                    String email = user.getEmail() != null ? user.getEmail() : "";
                    if (db != null) {
                        Map<String, Object> profile = new HashMap<>();
                        profile.put("name", name);
                        profile.put("email", email);
                        profile.put("last_login", FieldValue.serverTimestamp());
                        db.collection("users").document(uid).set(profile);
                    }
                    emitSignal("signed_in", uid, name, email);
                } else {
                    String err = authTask.getException() != null ? authTask.getException().getMessage() : "Firebase auth failed";
                    emitSignal("sign_in_failed", err != null ? err : "Firebase auth failed");
                }
            });
        } catch (ApiException e) {
            emitSignal("sign_in_failed", "Google Sign-In error code " + e.getStatusCode());
        } catch (Exception e) {
            emitSignal("sign_in_failed", e.getMessage() != null ? e.getMessage() : "Sign-in failed");
        }
    }

    @UsedByGodot
    public void sign_out() {
        Activity activity = getActivity();
        try {
            if (auth != null) {
                auth.signOut();
            }
            if (activity != null) {
                buildGoogleClient(activity).signOut();
            }
        } catch (Exception e) {
            Log.w(TAG, "Sign out warning: " + e.getMessage());
        }
        emitSignal("signed_out");
    }

    @UsedByGodot
    public void delete_account() {
        Activity activity = getActivity();
        FirebaseUser user = auth != null ? auth.getCurrentUser() : null;
        if (user == null) {
            emitSignal("account_deleted");
            return;
        }
        String uid = user.getUid();
        if (db != null) {
            db.collection("users").document(uid).delete();
            for (String trackId : ALL_TRACKS) {
                db.collection("leaderboards").document(trackId)
                        .collection("entries").document(uid).delete();
            }
        }
        user.delete().addOnCompleteListener(task -> {
            if (task.isSuccessful()) {
                if (activity != null) {
                    try {
                        buildGoogleClient(activity).signOut();
                    } catch (Exception ignored) {
                    }
                }
                emitSignal("account_deleted");
            } else {
                String err = task.getException() != null ? task.getException().getMessage() : "Re-sign-in required to delete account";
                emitSignal("delete_failed", err != null ? err : "Delete failed");
            }
        });
    }

    @UsedByGodot
    public void submit_score(String trackId, long timeMs, String carId) {
        FirebaseUser user = auth != null ? auth.getCurrentUser() : null;
        if (user == null || db == null || trackId == null || trackId.isEmpty() || timeMs <= 0) {
            emitSignal("score_submitted", trackId != null ? trackId : "", false);
            return;
        }
        String uid = user.getUid();
        String name = user.getDisplayName() != null ? user.getDisplayName() : "Racer";
        DocumentReference docRef = db.collection("leaderboards")
                .document(trackId)
                .collection("entries")
                .document(uid);

        docRef.get().addOnCompleteListener(getTask -> {
            if (getTask.isSuccessful()) {
                DocumentSnapshot snap = getTask.getResult();
                if (snap != null && snap.exists()) {
                    Long existing = snap.getLong("time_ms");
                    if (existing != null && existing > 0 && existing <= timeMs) {
                        emitSignal("score_submitted", trackId, true);
                        return;
                    }
                }
            }
            Map<String, Object> entry = new HashMap<>();
            entry.put("uid", uid);
            entry.put("name", name);
            entry.put("time_ms", timeMs);
            entry.put("car", carId != null ? carId : "yellow");
            entry.put("updated_at", FieldValue.serverTimestamp());
            docRef.set(entry).addOnCompleteListener(setTask ->
                    emitSignal("score_submitted", trackId, setTask.isSuccessful()));
        });
    }

    @UsedByGodot
    public void fetch_leaderboard(String trackId, int limit) {
        if (db == null || trackId == null || trackId.isEmpty()) {
            emitSignal("leaderboard_loaded", trackId != null ? trackId : "", "[]");
            return;
        }
        int safeLimit = Math.max(1, Math.min(limit, 50));
        db.collection("leaderboards")
                .document(trackId)
                .collection("entries")
                .orderBy("time_ms", Query.Direction.ASCENDING)
                .limit(safeLimit)
                .get()
                .addOnCompleteListener(task -> {
                    JSONArray arr = new JSONArray();
                    if (task.isSuccessful() && task.getResult() != null) {
                        for (QueryDocumentSnapshot doc : task.getResult()) {
                            try {
                                JSONObject item = new JSONObject();
                                item.put("uid", doc.getId());
                                item.put("name", doc.getString("name") != null ? doc.getString("name") : "Racer");
                                Long ms = doc.getLong("time_ms");
                                item.put("time_ms", ms != null ? ms : 0L);
                                item.put("car", doc.getString("car") != null ? doc.getString("car") : "yellow");
                                arr.put(item);
                            } catch (Exception ignored) {
                            }
                        }
                    }
                    emitSignal("leaderboard_loaded", trackId, arr.toString());
                });
    }
}
