# Nextcloud app "untrash": English source -> (German, French).
# German: the neutral form of the UntrashOS catalogs (infinitives, no du/Sie),
# used for both "de" and "de_DE".  Nextcloud's own terms as Nextcloud
# translates them ("Auf Änderungen prüfen", "Nie"; "Rechercher les
# modifications", "Jamais").  build.py writes untrash/l10n/.
T = {
    "(this Nextcloud)": ("(diese Nextcloud)", "(ce Nextcloud)"),
    "An admin removed this Nextcloud from the mesh {mesh}. It no longer keeps the address book. To join again, leave the mesh here and paste a new invitation.":
        ("Ein Admin hat diese Nextcloud aus dem Mesh {mesh} entfernt. Sie führt das Adressbuch nicht mehr. Für einen neuen Beitritt hier das Mesh verlassen und eine neue Einladung einfügen.",
         "Un administrateur a retiré ce Nextcloud du mesh {mesh}. Il ne tient plus le carnet d'adresses. Pour adhérer de nouveau, quittez le mesh ici et collez une nouvelle invitation."),
    "Change feed": ("Änderungsliste", "Flux des modifications"),
    "Directory address:": ("Adresse des Verzeichnisses:", "Adresse de l'annuaire :"),
    "Endpoints": ("Endpunkte", "Points d'accès"),
    "Enter the address as http://NAS:5002/untrash-cloudlink or https://NAS:5003/untrash-cloudlink.":
        ("Adresse als http://NAS:5002/untrash-cloudlink oder https://NAS:5003/untrash-cloudlink eingeben.",
         "Saisissez l'adresse sous la forme http://NAS:5002/untrash-cloudlink ou https://NAS:5003/untrash-cloudlink."),
    "For each NAS, the address of its WebDAV port with /untrash-cloudlink. External storages (WebDAV) whose URL is that NAS and whose folder is webdav/<share> are then updated path by path; set their \"Check for changes\" to \"Never\". The changes arrive every 5 minutes with the background jobs, or within seconds while \"occ untrash:feed\" runs as a service.":
        ("Für jedes NAS die Adresse seines WebDAV-Ports mit /untrash-cloudlink. Externe Speicher (WebDAV), deren URL dieses NAS ist und deren Ordner webdav/<Freigabe> ist, werden dann Pfad für Pfad aktualisiert; bei ihnen \"Auf Änderungen prüfen\" auf \"Nie\" stellen. Die Änderungen kommen alle 5 Minuten mit den Hintergrundjobs, oder innerhalb von Sekunden, solange \"occ untrash:feed\" als Dienst läuft.",
         "Pour chaque NAS, l'adresse de son port WebDAV avec /untrash-cloudlink. Les stockages externes (WebDAV) dont l'URL est ce NAS et dont le dossier est webdav/<partage> sont alors mis à jour chemin par chemin ; réglez leur « Rechercher les modifications » sur « Jamais ». Les modifications arrivent toutes les 5 minutes avec les tâches de fond, ou en quelques secondes tant que « occ untrash:feed » tourne comme service."),
    "The HTTPS key at this address is not the one the NAS signed in the mesh. Check the address; if the NAS made a new certificate, wait until its new mesh record has arrived.":
        ("Der HTTPS-Schlüssel unter dieser Adresse ist nicht der, den das NAS im Mesh signiert hat. Adresse prüfen; hat das NAS ein neues Zertifikat erstellt, warten, bis sein neuer Mesh-Eintrag angekommen ist.",
         "La clé HTTPS à cette adresse n'est pas celle que le NAS a signée dans le mesh. Vérifiez l'adresse ; si le NAS a créé un nouveau certificat, attendez que sa nouvelle fiche du mesh soit arrivée."),
    "HTTPS key pinned through the mesh": ("HTTPS-Schlüssel über das Mesh gepinnt", "Clé HTTPS épinglée par le mesh"),
    "Invitation": ("Einladung", "Invitation"),
    "Join": ("Beitreten", "Adhérer"),
    "Join a mesh": ("Einem Mesh beitreten", "Adhérer à un mesh"),
    "Joined.": ("Beigetreten.", "Adhésion faite."),
    "Joining …": ("Beitritt läuft …", "Adhésion en cours …"),
    "Kind": ("Art", "Type"),
    "Leave the mesh": ("Mesh verlassen", "Quitter le mesh"),
    "Leave the mesh? The NAS admin can remove this Nextcloud there too.":
        ("Mesh verlassen? Der Admin des NAS kann diese Nextcloud auch dort entfernen.",
         "Quitter le mesh ? L'administrateur du NAS peut aussi retirer ce Nextcloud de son côté."),
    "Left the mesh.": ("Mesh verlassen.", "Mesh quitté."),
    "Member": ("Mitglied", "Membre"),
    "Member of {mesh} as {name}.": ("Mitglied von {mesh} als {name}.", "Membre de {mesh} sous le nom {name}."),
    "Name in the mesh": ("Name im Mesh", "Nom dans le mesh"),
    "No NAS in the mesh.": ("Kein NAS im Mesh.", "Aucun NAS dans le mesh."),
    "No address for this NAS yet.": ("Für dieses NAS ist noch keine Adresse eingetragen.", "Pas encore d'adresse pour ce NAS."),
    "On the UntrashOS NAS choose UntrashMesh → Connect a Nextcloud and paste the invitation here. This server must reach the NAS while it joins.":
        ("Auf dem UntrashOS-NAS UntrashMesh → Nextcloud verbinden wählen und die Einladung hier einfügen. Während des Beitritts muss dieser Server das NAS erreichen.",
         "Sur le NAS UntrashOS, choisissez UntrashMesh → Connecter un Nextcloud et collez l'invitation ici. Pendant l'adhésion, ce serveur doit joindre le NAS."),
    "Reached {nas} (UntrashOS {version}), shares: {shares}":
        ("{nas} erreicht (UntrashOS {version}), Freigaben: {shares}", "{nas} joint (UntrashOS {version}), partages : {shares}"),
    "Record from": ("Eintrag vom", "Fiche du"),
    "Save": ("Speichern", "Enregistrer"),
    "Saved.": ("Gespeichert.", "Enregistré."),
    "Test": ("Testen", "Tester"),
    "The NAS answered HTTP %s. Is WebDAV on, and is this the address of its WebDAV port?":
        ("Das NAS hat mit HTTP %s geantwortet. Ist WebDAV an, und ist das die Adresse seines WebDAV-Ports?",
         "Le NAS a répondu HTTP %s. WebDAV est-il activé, et est-ce l'adresse de son port WebDAV ?"),
    "The NAS did not take this Nextcloud in.": ("Das NAS hat diese Nextcloud nicht aufgenommen.", "Le NAS n'a pas accueilli ce Nextcloud."),
    "The NAS is not reachable (%s). It must be reachable from this server while the Nextcloud joins.":
        ("Das NAS ist nicht erreichbar (%s). Während des Beitritts muss es von diesem Server aus erreichbar sein.",
         "Le NAS n'est pas joignable (%s). Il doit être joignable depuis ce serveur pendant l'adhésion du Nextcloud."),
    "The NAS is not reachable: %s": ("Das NAS ist nicht erreichbar: %s", "Le NAS n'est pas joignable : %s"),
    "The NAS refused the invitation: it was used already, or it is not for a Nextcloud.":
        ("Das NAS hat die Einladung abgelehnt: Sie wurde schon benutzt oder ist nicht für eine Nextcloud.",
         "Le NAS a refusé l'invitation : elle a déjà servi, ou elle n'est pas destinée à un Nextcloud."),
    "The NAS refused this Nextcloud: %s": ("Das NAS hat diese Nextcloud abgewiesen: %s", "Le NAS a refusé ce Nextcloud : %s"),
    "The answer is not from the inviting NAS.": ("Die Antwort kommt nicht vom einladenden NAS.", "La réponse ne vient pas du NAS qui a invité."),
    "The invitation has expired.": ("Die Einladung ist abgelaufen.", "L'invitation a expiré."),
    "This Nextcloud can join an UntrashMesh, the encrypted network of UntrashOS devices. It keeps the mesh's address book at its internet address, so members that lost each other find each other again, and it follows the changes in the shares of a linked NAS, so external storages on that NAS need no scanning.":
        ("Diese Nextcloud kann einem UntrashMesh beitreten, dem verschlüsselten Netz der UntrashOS-Geräte. Sie führt das Adressbuch des Mesh unter ihrer Internetadresse, so finden Mitglieder, die sich verloren haben, wieder zueinander. Außerdem folgt sie den Änderungen in den Freigaben eines verbundenen NAS, so müssen externe Speicher auf diesem NAS nicht durchsucht werden.",
         "Ce Nextcloud peut adhérer à un UntrashMesh, le réseau chiffré des appareils UntrashOS. Il tient le carnet d'adresses du mesh à son adresse internet : les membres qui se sont perdus se retrouvent. Il suit aussi les modifications dans les partages d'un NAS relié : les stockages externes sur ce NAS n'ont pas besoin d'être parcourus."),
    "This Nextcloud is in a mesh already. Leave it first.":
        ("Diese Nextcloud ist schon in einem Mesh. Erst dieses verlassen.", "Ce Nextcloud est déjà dans un mesh. Quittez-le d'abord."),
    "This invitation is not for a Nextcloud. On the NAS choose UntrashMesh → Connect a Nextcloud.":
        ("Diese Einladung ist nicht für eine Nextcloud. Auf dem NAS UntrashMesh → Nextcloud verbinden wählen.",
         "Cette invitation n'est pas destinée à un Nextcloud. Sur le NAS, choisissez UntrashMesh → Connecter un Nextcloud."),
    "This is not an UntrashMesh invitation.": ("Das ist keine UntrashMesh-Einladung.", "Ce n'est pas une invitation UntrashMesh."),
    "Unknown member.": ("Unbekanntes Mitglied.", "Membre inconnu."),
    "admin": ("Admin", "admin"),
    "check the HTTPS certificate": ("HTTPS-Zertifikat prüfen", "vérifier le certificat HTTPS"),
    "last round {time}: {changes} changes": ("letzte Runde {time}: {changes} Änderungen", "dernier passage {time} : {changes} modifications"),
    "not linked there": ("dort nicht verbunden", "pas relié là-bas"),
    "Tunnel connected": ("Tunnel verbunden", "Tunnel connecté"),
    "Use the mesh address": ("Mesh-Adresse verwenden", "Utiliser l'adresse du mesh"),
    "Tunnel: no connection from this NAS yet": ("Tunnel: noch keine Verbindung von diesem NAS", "Tunnel : pas encore de connexion de ce NAS"),
    "Tunnel: this server is a WireGuard peer of the mesh at {endpoints}. The NAS connect to it, so it reaches them at their mesh address.":
        ("Tunnel: Dieser Server ist unter {endpoints} ein WireGuard-Partner des Mesh. Die NAS verbinden sich zu ihm, so erreicht er sie unter ihrer Mesh-Adresse.",
         "Tunnel : ce serveur est un pair WireGuard du mesh à {endpoints}. Les NAS se connectent à lui : il les joint à leur adresse du mesh."),
    "No tunnel: this server reaches a NAS only at the address entered below. With the helper untrash-cloud-wg on this server it reaches a NAS behind a router without a port forward (see the app README).":
        ("Kein Tunnel: Dieser Server erreicht ein NAS nur unter der unten eingetragenen Adresse. Mit dem Hilfsdienst untrash-cloud-wg auf diesem Server erreicht er ein NAS hinter einem Router ohne Portweiterleitung (siehe README der App).",
         "Pas de tunnel : ce serveur ne joint un NAS qu'à l'adresse saisie ci-dessous. Avec l'assistant untrash-cloud-wg sur ce serveur, il joint un NAS derrière un routeur sans redirection de port (voir le README de l'app)."),
}
