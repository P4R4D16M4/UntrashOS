# UntrashOS UI catalog, part M: English source -> (German, French), the
# security fixes of 1.2-rc3 (security check 2026-11-03: no unencrypted Desk
# sign-in over the internet, UPnP forwarding warnings).
T = {
    "Forwarded services are reachable from the internet. Over FTP, WebDAV and Web Publishing without HTTPS, passwords cross the internet unencrypted: forward only HTTPS services.":
        ("Weitergeleitete Dienste sind aus dem Internet erreichbar. Über FTP, WebDAV und Web Publishing ohne HTTPS gehen Passwörter unverschlüsselt durch das Internet: nur HTTPS-Dienste weiterleiten.",
         "Les services redirigés sont joignables depuis internet. Par FTP, WebDAV et Web Publishing sans HTTPS, les mots de passe traversent internet en clair : ne redirigez que des services HTTPS."),
    "The Desk is forwarded only over HTTPS: over HTTP the sign-in would cross the internet unencrypted.":
        ("Die Desk wird nur über HTTPS weitergeleitet: Über HTTP ginge die Anmeldung unverschlüsselt durch das Internet.",
         "La Desk n'est redirigée qu'en HTTPS : en HTTP, la connexion traverserait internet en clair."),
    "never forwarded: the sign-in would be unencrypted":
        ("wird nie weitergeleitet: die Anmeldung wäre unverschlüsselt",
         "jamais redirigé : la connexion serait en clair"),
    "Over the internet the Desk signs in only over HTTPS (Settings → Certificate, HTTPS).":
        ("Über das Internet meldet sich die Desk nur über HTTPS an (Einstellungen → Zertifikat, HTTPS).",
         "Par internet, la Desk ne se connecte qu'en HTTPS (Réglages → Certificat, HTTPS)."),
}
