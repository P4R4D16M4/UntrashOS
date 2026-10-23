# UntrashOS UI catalog, part H: installer plan steps, job log and problems as
# whole sentences (fragments alone would leave mixed-language lines).
T = {
    # detail heading, buttons
    "Weg A": ("Way A", "Voie A"),
    "Weg B": ("Way B", "Voie B"),
    "Weg C": ("Way C", "Voie C"),
    "Weg D": ("Way D", "Voie D"),
    "Starten": ("Start", "Démarrer"),
    "Stock-Konfiguration": ("Stock configuration", "Configuration d'origine"),
    # way A
    "Partitionstabelle und RAID/LVM-Metadaten von %s auf den Stick sichern": (
        "Back up the partition table and RAID/LVM metadata of %s to the stick",
        "Sauvegarder sur la clé la table de partitions et les métadonnées RAID/LVM de %s"),
    "Stock-Volumes freigeben, RAID-Verbände der Platte stoppen": (
        "Release the stock volumes, stop the RAID arrays of the disk",
        "Libérer les volumes d'origine, arrêter les grappes RAID du disque"),
    "ALLE Partitionen und Daten auf %s (%s, %.0f GB) löschen": (
        "Erase ALL partitions and data on %s (%s, %.0f GB)",
        "Effacer TOUTES les partitions et données de %s (%s, %.0f Go)"),
    "UntrashOS-Layout anlegen: ut-sys-a/b, ut-state, ut-swap, ut-data, ut-bootstate": (
        "Create the UntrashOS layout: ut-sys-a/b, ut-state, ut-swap, ut-data, ut-bootstate",
        "Créer la disposition UntrashOS : ut-sys-a/b, ut-state, ut-swap, ut-data, ut-bootstate"),
    "Systemabbild %s nach ut-sys-a und ut-sys-b schreiben und zurücklesen": (
        "Write system image %s to ut-sys-a and ut-sys-b and read it back",
        "Écrire l'image système %s dans ut-sys-a et ut-sys-b et la relire"),
    "Datenbereich ut-data mit btrfs formatieren": (
        "Format the data area ut-data with btrfs", "Formater la zone de données ut-data en btrfs"),
    "Achtung: Der Stock-Verband %s (%s) verliert damit eine Platte und ist danach unvollständig": (
        "Caution: the stock array %s (%s) loses a disk and is incomplete afterwards",
        "Attention : la grappe d'origine %s (%s) perd ainsi un disque et sera incomplète"),
    "%s trägt das laufende System und kann von hier nicht gelöscht werden.": (
        "%s holds the running system and cannot be erased from here.",
        "%s porte le système en cours et ne peut pas être effacé d'ici."),
    # ways B/C
    "Partitionstabellen und RAID/LVM-Metadaten der Platten von „%s“ auf den Stick sichern": (
        "Back up the partition tables and RAID/LVM metadata of the disks of “%s” to the stick",
        "Sauvegarder sur la clé les tables de partitions et métadonnées RAID/LVM des disques de « %s »"),
    "Volume „%s“ (%s, %s) beschreibbar einbinden; keine Partition und kein Verband wird verändert": (
        "Mount volume “%s” (%s, %s) writable; no partition and no array is changed",
        "Monter le volume « %s » (%s, %s) en écriture ; aucune partition ni grappe n'est modifiée"),
    "Systemabbild %s zweimal als /.untrash/slot-a/b.utslot ablegen und zurücklesen (%.1f GB)": (
        "Store system image %s twice as /.untrash/slot-a/b.utslot and read it back (%.1f GB)",
        "Déposer l'image système %s deux fois en /.untrash/slot-a/b.utslot et la relire (%.1f Go)"),
    "Zustand (/.untrash/state.img, 4 GiB) und Auslagerung (/.untrash/swap.img, 1 GiB) anlegen": (
        "Create the state (/.untrash/state.img, 4 GiB) and swap (/.untrash/swap.img, 1 GiB)",
        "Créer l'état (/.untrash/state.img, 4 Gio) et le swap (/.untrash/swap.img, 1 Gio)"),
    "Zustand (/.untrash/state.img, 4 GiB) und Auslagerung (/.untrash/swap.img, 1 GiB) anlegen – vorhandener Zustand bleibt": (
        "Create the state (/.untrash/state.img, 4 GiB) and swap (/.untrash/swap.img, 1 GiB) – the existing state is kept",
        "Créer l'état (/.untrash/state.img, 4 Gio) et le swap (/.untrash/swap.img, 1 Gio) – l'état existant est conservé"),
    "Boot-Zähler /.untrash/bootstate schreiben, Marker UNTRASH/INSTALL vom Stick entfernen": (
        "Write the boot counter /.untrash/bootstate, remove the marker UNTRASH/INSTALL from the stick",
        "Écrire le compteur de démarrage /.untrash/bootstate, retirer le marqueur UNTRASH/INSTALL de la clé"),
    "Stock-Konfiguration nach /.untrash/stock-config; beim ersten Start übernimmt UntrashOS Benutzer, Gruppen, Freigaben und SMB-Passwörter": (
        "Stock configuration to /.untrash/stock-config; on the first start UntrashOS takes over users, groups, shares and SMB passwords",
        "Configuration d'origine vers /.untrash/stock-config ; au premier démarrage UntrashOS reprend utilisateurs, groupes, partages et mots de passe SMB"),
    "Neue Konfiguration: Benutzer admin mit dem Passwort von unten (SMB, SSH), Name im Netz wie unten, %d Freigabe(n) für admin (lesen/schreiben): %s": (
        "New configuration: user admin with the password below (SMB, SSH), network name as below, %d share(s) for admin (read/write): %s",
        "Nouvelle configuration : utilisateur admin avec le mot de passe ci-dessous (SMB, SSH), nom réseau comme ci-dessous, %d partage(s) pour admin (lecture/écriture) : %s"),
    "Der Verband von „%s“ ist unvollständig (%d Platte(n) gefunden); erst alle Platten einsetzen – der Loader schreibt auf unvollständige Verbände nie.": (
        "The array of “%s” is incomplete (%d disk(s) found); insert all disks first – the loader never writes to incomplete arrays.",
        "La grappe de « %s » est incomplète (%d disque(s) trouvé(s)) ; insérez d'abord tous les disques – le chargeur n'écrit jamais sur une grappe incomplète."),
    "Eine Platte trägt UntrashOS-Partitionen (Weg A); der Loader startet diese vor /.untrash. Diese Platte zuerst entfernen.": (
        "A disk carries UntrashOS partitions (way A); the loader starts these before /.untrash. Remove this disk first.",
        "Un disque porte des partitions UntrashOS (voie A) ; le chargeur les démarre avant /.untrash. Retirez d'abord ce disque."),
    "Das Passwort für admin braucht mindestens 8 Zeichen.": (
        "The password for admin needs at least 8 characters.", "Le mot de passe d'admin doit compter au moins 8 caractères."),
    "Die beiden Passwörter stimmen nicht überein.": ("The two passwords do not match.", "Les deux mots de passe ne correspondent pas."),
    "Name im Netz: 1–15 Zeichen, Buchstaben, Ziffern und Bindestrich.": (
        "Network name: 1–15 characters, letters, digits and hyphen.",
        "Nom réseau : 1 à 15 caractères, lettres, chiffres et trait d'union."),
    "Kein einhängbares ext4-Stock-Volume: %s": ("No mountable ext4 stock volume: %s", "Aucun volume d'origine ext4 montable : %s"),
    "Read-only-Prüfung von RAID/LVM/Dateisystem fehlgeschlagen: %s": (
        "Read-only check of RAID/LVM/file system failed: %s", "Échec de la vérification en lecture seule RAID/LVM/système de fichiers : %s"),
    "e2fsck %s meldet Fehler (rc %d); bitte zuerst prüfen": (
        "e2fsck %s reports errors (rc %d); please check first", "e2fsck %s signale des erreurs (rc %d) ; veuillez d'abord vérifier"),
    # way D
    "Prüfsummen der Sicherung %s prüfen (%d Dateien)": (
        "Check the checksums of backup %s (%d files)", "Vérifier les sommes de contrôle de la sauvegarde %s (%d fichiers)"),
    "Prüfsummen der Sicherung %s prüfen (%d Dateien, beim Anlegen zurückgelesen)": (
        "Check the checksums of backup %s (%d files, read back when it was made)",
        "Vérifier les sommes de contrôle de la sauvegarde %s (%d fichiers, relus à la création)"),
    "Marker UNTRASH/ROLLBACK auf den Stick schreiben und neu starten": (
        "Write the marker UNTRASH/ROLLBACK to the stick and restart",
        "Écrire le marqueur UNTRASH/ROLLBACK sur la clé et redémarrer"),
    "Die NAS startet einmal die Stock-Firmware; diese schreibt Env und kernel%s aus der Sicherung zurück und schaltet aus (Stick stecken lassen)": (
        "The NAS starts the stock firmware once; it writes env and kernel%s back from the backup and powers off (leave the stick in)",
        "Le NAS démarre une fois le firmware d'origine ; celui-ci réécrit env et kernel%s depuis la sauvegarde et s'éteint (laisser la clé branchée)"),
    "Danach einschalten: Stock-Firmware wie vor der Installation; Daten auf den Platten bleiben, UntrashOS-Dateien in /.untrash bzw. die UntrashOS-Platte bleiben liegen": (
        "Then power on: stock firmware as before the installation; data on the disks stays, the UntrashOS files in /.untrash or the UntrashOS disk are left in place",
        "Ensuite, allumer : firmware d'origine comme avant l'installation ; les données des disques restent, les fichiers UntrashOS dans /.untrash ou le disque UntrashOS sont laissés en place"),
    "%s ist keine abgeschlossene Installations-Sicherung; der Stock-Zustand steht in der install-*-Sicherung mit device.env.": (
        "%s is not a completed installation backup; the stock state is in the install-* backup with device.env.",
        "%s n'est pas une sauvegarde d'installation terminée ; l'état d'origine se trouve dans la sauvegarde install-* avec device.env."),
    # start / job log
    "Bestätigungstext stimmt nicht (erwartet: %s).": ("Confirmation text does not match (expected: %s).",
                                                     "Le texte de confirmation ne correspond pas (attendu : %s)."),
    "Es läuft bereits ein Vorgang.": ("An operation is already running.", "Une opération est déjà en cours."),
    "Es läuft noch ein Vorgang.": ("An operation is still running.", "Une opération est encore en cours."),
    "Probelauf: kein Neustart.": ("Dry run: no restart.", "Essai à blanc : pas de redémarrage."),
    "(Probelauf: COPY-Taste als gedrückt angenommen)": ("(Dry run: COPY button assumed pressed)",
                                                       "(Essai à blanc : touche COPY considérée comme appuyée)"),
    "COPY-Taste erkannt.": ("COPY button detected.", "Touche COPY détectée."),
    "%s zurückgelesen: identisch": ("%s read back: identical", "%s relu : identique"),
    "Rücklesen von %s stimmt nicht (%s)": ("Read-back of %s does not match (%s)", "La relecture de %s ne correspond pas (%s)"),
    "Rücklesen von %s stimmt nicht (Kopf %s, Trailer %s)": ("Read-back of %s does not match (head %s, trailer %s)",
                                                           "La relecture de %s ne correspond pas (en-tête %s, fin %s)"),
    "%s/%s passt nicht zur Prüfsumme der Installation": ("%s/%s does not match the installation checksum",
                                                         "%s/%s ne correspond pas à la somme de contrôle de l'installation"),
    "FEHLER: %s": ("ERROR: %s", "ERREUR : %s"),
    "Marker UNTRASH/ROLLBACK gesetzt. Die NAS startet jetzt neu, startet einmal die Stock-Firmware, schreibt Env und kernel%s aus der Sicherung zurück und schaltet sich dann aus (einige Minuten; der Stick muss stecken bleiben). Danach einschalten: die NAS startet die Stock-Firmware wie vor der Installation.": (
        "Marker UNTRASH/ROLLBACK set. The NAS now restarts, starts the stock firmware once, writes env and kernel%s back from the backup and then powers off (a few minutes; the stick must stay in). Then power on: the NAS starts the stock firmware as before the installation.",
        "Marqueur UNTRASH/ROLLBACK posé. Le NAS redémarre, démarre une fois le firmware d'origine, réécrit env et kernel%s depuis la sauvegarde puis s'éteint (quelques minutes ; la clé doit rester branchée). Ensuite, allumer : le NAS démarre le firmware d'origine comme avant l'installation."),
    "Weg A: Neuinstallation – Platte löschen": ("Way A: new installation – erase the disk", "Voie A : nouvelle installation – effacer le disque"),
    "Weg A: Neuinstallation – Platte löschen (PROBELAUF)": ("Way A: new installation – erase the disk (DRY RUN)",
                                                           "Voie A : nouvelle installation – effacer le disque (ESSAI À BLANC)"),
    "Weg B: Neuinstallation – Daten behalten, alte Benutzer und Freigaben übernehmen": (
        "Way B: new installation – keep the data, take over the old users and shares",
        "Voie B : nouvelle installation – conserver les données, reprendre les anciens utilisateurs et partages"),
    "Weg B: Neuinstallation – Daten behalten, alte Benutzer und Freigaben übernehmen (PROBELAUF)": (
        "Way B: new installation – keep the data, take over the old users and shares (DRY RUN)",
        "Voie B : nouvelle installation – conserver les données, reprendre les anciens utilisateurs et partages (ESSAI À BLANC)"),
    "Weg C: Neuinstallation – Daten behalten, neue Benutzer und Einstellungen": (
        "Way C: new installation – keep the data, new users and settings",
        "Voie C : nouvelle installation – conserver les données, nouveaux utilisateurs et réglages"),
    "Weg C: Neuinstallation – Daten behalten, neue Benutzer und Einstellungen (PROBELAUF)": (
        "Way C: new installation – keep the data, new users and settings (DRY RUN)",
        "Voie C : nouvelle installation – conserver les données, nouveaux utilisateurs et réglages (ESSAI À BLANC)"),
    "Weg D: Stock-Firmware aus der Sicherung auf dem Stick wiederherstellen": (
        "Way D: restore the stock firmware from the backup on the stick",
        "Voie D : restaurer le firmware d'origine depuis la sauvegarde sur la clé"),
    "Weg D: Stock-Firmware aus der Sicherung auf dem Stick wiederherstellen (PROBELAUF)": (
        "Way D: restore the stock firmware from the backup on the stick (DRY RUN)",
        "Voie D : restaurer le firmware d'origine depuis la sauvegarde sur la clé (ESSAI À BLANC)"),
    # single words the extractor does not recognise as German (no umlaut/stop word)
    "Herunterladen": ("Download", "Télécharger"),
    "Art": ("Type", "Type"),
    "RAID-Typ": ("RAID type", "Type de RAID"),
    "Zum Bestätigen %s eintippen": ("Type %s to confirm", "Tapez %s pour confirmer"),
    "Audio": ("Audio", "Audio"),
    "Benutzername": ("User name", "Nom d'utilisateur"),
    # weekday abbreviations (mail report, backup schedule)
    "Mo": ("Mon", "lun."), "Di": ("Tue", "mar."), "Mi": ("Wed", "mer."), "Do": ("Thu", "jeu."),
    "Fr": ("Fri", "ven."), "Sa": ("Sat", "sam."), "So": ("Sun", "dim."),
    # cloud / backup dialogs (found in the guide screenshots)
    "%s verbinden": ("Connect %s", "Connecter %s"),
    # the trailing ":" stays in the page; the phrase match keeps it
    "Die komplette Adresse aus der Adresszeile dieser Seite kopieren und hier einfügen": (
        "Copy the complete address from that page's address bar and paste it here",
        "Copier l'adresse complète depuis la barre d'adresse de cette page et la coller ici"),
    "Ordner (leer = ganze Freigabe)": ("Folder (empty = whole share)", "Dossier (vide = tout le partage)"),
    "Bandbreite KB/s (0 = frei)": ("Bandwidth KB/s (0 = unlimited)", "Bande passante Ko/s (0 = illimitée)"),
    "ab %s Platte(n)": ("from %s disk(s)", "dès %s disque(s)"),
    # schedules, cloud, iSCSI (found by the guide inventory)
    "monatlich": ("monthly", "mensuel"),
    "Zwei-Wege-Sync": ("two-way sync", "synchronisation bidirectionnelle"),
    "CHAP-Benutzername": ("CHAP user name", "Nom d'utilisateur CHAP"),
    "CHAP-Passwort (12–16 Zeichen; leer = behalten)": ("CHAP password (12–16 characters; empty = keep)",
                                                      "Mot de passe CHAP (12 à 16 caractères ; vide = conserver)"),
    "iSCSI-Ziel": ("iSCSI target", "Cible iSCSI"),
    "Rsync-Server": ("Rsync server", "Serveur rsync"),
    # user manual (Desk app, login page)
    "Handbuch": ("Manual", "Manuel"),
    "Bedienungsanleitung": ("User guide", "Mode d'emploi"),
    "Bedienungsanleitung (Englisch)": ("User guide (English)", "Mode d'emploi (anglais)"),
    "PDF herunterladen": ("Download PDF", "Télécharger le PDF"),
    "In neuem Tab öffnen": ("Open in a new tab", "Ouvrir dans un nouvel onglet"),
}
