"""Textes pédagogiques du cas intégrateur « consolidation du Groupe Saint-Maurice » (chiffrier du cours).

Repris du classeur Chiffrier_consolidation_Groupe_Saint-Maurice.xlsx : une explication par écriture de consolidation et les notes des étapes
de conversion, d'acquisition et de participation ne donnant pas le contrôle.
"""

EXPLICATIONS = {'E1': {'famille': 'Opérations réciproques',
        'operation': 'Honoraires de gestion facturés par la société mère',
        'pourquoi': "Produits et charges disparaissent du même montant : le résultat consolidé ne bouge pas, mais le chiffre d'affaires du groupe, "
                    "oui. Ne pas éliminer reviendrait à présenter comme un produit une facture que le groupe s'est adressée à lui-même."},
 'E2': {'famille': 'Opérations réciproques',
        'operation': "Loyer facturé par l'immobilière à l'opérante",
        'pourquoi': "Même logique. Attention à l'effet caché : après élimination, le groupe n'a plus de charge de loyer mais porte l'amortissement "
                    "de l'immeuble et les intérêts hypothécaires. La structure de coûts consolidée n'a plus rien à voir avec celle de l'opérante "
                    'seule.'},
 'E3': {'famille': 'Opérations réciproques',
        'operation': 'Ventes de Usinage SM à USM Precision — vente aval',
        'pourquoi': "On élimine toujours 100 % de l'opération, jamais la quote-part de détention. Ici la filiale est détenue à 100 %, mais la règle "
                    'vaut aussi à 80 %.'},
 'E4': {'famille': 'Opérations réciproques',
        'operation': 'Ventes de Soudure Bécancour à Usinage SM — vente amont',
        'pourquoi': "Soudure Bécancour n'est détenue qu'à 80 %, et pourtant les 950 000 $ sont éliminés en entier. C'est l'attribution du résultat "
                    'aux minoritaires, plus loin, qui rétablit le partage. Éliminer 80 % laisserait un solde intersociétés qui ne balance pas.'},
 'E5': {'famille': 'Profits non réalisés',
        'operation': 'Marge incluse dans les stocks encore détenus par le groupe',
        'pourquoi': "La seule famille qui change vraiment le résultat consolidé. Tant qu'un client externe n'a pas acheté, le profit n'existe pas "
                    'pour le groupe : on le retire du résultat et de la valeur du stock. On élimine la marge du vendeur, pas la marge moyenne du '
                    'groupe.'},
 'E6': {'famille': 'Profits non réalisés',
        'operation': 'Impôts différés sur le profit non réalisé',
        'pourquoi': "Soudure Bécancour a déjà payé l'impôt sur un profit que le groupe ne reconnaît pas encore. L'écart crée un actif d'impôts "
                    'différés, qui se renversera au moment de la vente au client externe.'},
 'E7': {'famille': 'Soldes réciproques',
        'operation': 'Comptes intersociétés à recevoir et à payer',
        'pourquoi': "Le groupe ne peut pas se devoir de l'argent à lui-même. L'actif et le passif diminuent du même montant, le résultat ne bouge "
                    "pas. Test imparable : après élimination, le solde net doit être exactement nul, entité par entité et en devise d'origine."},
 'E8': {'famille': 'Soldes réciproques',
        'operation': 'Billet de la société mère à Soudure Bécancour',
        'pourquoi': "Un prêt intragroupe n'est pas de la dette du groupe. Conséquence directe : le ratio d'endettement consolidé est plus bas que la "
                    "somme des ratios individuels — c'est exactement ce que le prêteur veut voir."},
 'E9': {'famille': 'Opérations réciproques',
        'operation': 'Intérêts sur le billet intersociétés',
        'pourquoi': "Corollaire de E8. Nuance importante : bien qu'éliminés au consolidé, ces intérêts restent une charge réelle pour Soudure "
                    'Bécancour et sont donc conservés dans le calcul de la quote-part des minoritaires.'},
 'E10': {'famille': 'Dividendes',
         'operation': 'Dividende versé par Usinage SM à Gestion SM',
         'pourquoi': "Sans cette écriture, le résultat de l'opérante serait compté deux fois : une fois comme bénéfice de la filiale, une fois comme "
                     "produit de dividende chez la mère. C'est l'erreur qui gonfle le plus visiblement un résultat consolidé."},
 'E11': {'famille': 'Dividendes',
         'operation': 'Dividende de Soudure Bécancour revenant à Usinage SM',
         'pourquoi': "Seule la part intragroupe se croise — 80 % des 150 000 $. Le reste appartient à l'actionnaire minoritaire et suit un autre "
                     'chemin.'},
 'E12': {'famille': 'Dividendes',
         'operation': 'Dividende de Soudure Bécancour versé aux minoritaires',
         'pourquoi': "Ce dividende sort réellement du groupe : ce n'est pas une élimination mais une distribution. Il réduit la PNDC au bilan, pas "
                     "les bénéfices non répartis consolidés. À l'état des flux de trésorerie, c'est un flux de financement."},
 'E13': {'famille': 'Placements',
         'operation': 'Élimination du placement dans Usinage Saint-Maurice',
         'pourquoi': "Filiale détenue à 100 % depuis sa constitution : le placement égale le capital-actions, il n'y a ni écart d'acquisition ni "
                     'bénéfices non répartis antérieurs à neutraliser. Le cas le plus simple.'},
 'E14': {'famille': 'Placements',
         'operation': 'Élimination du placement dans Immeubles Saint-Maurice',
         'pourquoi': "Même situation. Remarquez qu'après élimination, seul le capital-actions de la société mère subsiste au bilan consolidé — "
                     'jamais celui des filiales.'},
 'E15': {'famille': 'Placements',
         'operation': 'Élimination du placement dans USM Precision',
         'pourquoi': 'Le capital-actions de la filiale américaine est converti au cours historique (1,3200), exactement le cours auquel le placement '
                     "a été inscrit chez la mère. Les deux montants coïncident donc, et l'écart de conversion reste intact dans les capitaux "
                     'propres.'},
 'E16': {'famille': 'Placements',
         'operation': 'Élimination du placement dans Soudure Bécancour et comptabilisation de la répartition du prix',
         'pourquoi': "L'écriture centrale. On annule le placement et les capitaux propres de la filiale à la date d'acquisition, on inscrit les "
                     "écarts de juste valeur et les incorporels que le vendeur n'avait jamais portés à son bilan, on reconnaît l'impôt différé qui "
                     "en découle, on fait apparaître la PNDC — et l'écart d'acquisition ferme l'écriture. Seuls les bénéfices non répartis "
                     'postérieurs au 1er avril subsistent au consolidé.'},
 'E17': {'famille': "Suivi de l'acquisition",
         'operation': 'Amortissement des écarts de juste valeur — 9 mois',
         'pourquoi': "L'écriture la plus souvent oubliée. Les écarts dégagés à l'acquisition ne restent pas gelés : ils se consomment. Sans elle, le "
                     "résultat consolidé est surévalué chaque année jusqu'à la fin des durées d'amortissement."},
 'E18': {'famille': "Suivi de l'acquisition",
         'operation': "Reprise des impôts différés sur l'amortissement",
         'pourquoi': "Le passif d'impôts différés créé en E16 se dénoue au même rythme que l'amortissement des écarts auxquels il se rattache."},
 'E19': {'famille': 'Attribution',
         'operation': 'Attribution du résultat aux actionnaires minoritaires',
         'pourquoi': 'Dernière écriture, et pas une élimination : une répartition. Le résultat consolidé est présenté en entier, puis scindé entre '
                     "la société mère et les minoritaires. Le calcul détaillé est à l'étape 07."}}

NOTES = {'juste_valeur_impot': 'Un écart de JV crée une différence temporaire : la valeur comptable monte, la valeur fiscale ne bouge pas.',
 'ecart_acquisition': "Résidu, jamais une donnée. En NCECF il ne s'amortit pas ; on le teste lorsque des indices de dépréciation existent (3064).",
 'ifrs': "Le chapitre 1582 impose la juste valeur ; IFRS 3 laisse le choix. D'où deux écarts d'acquisition possibles pour la même transaction.",
 'amortissement_ppa': "Cet amortissement n'existe que dans le chiffrier : les livres de Soudure Bécancour ne le connaissent pas. Il faut donc le "
                      "recréer chaque exercice, avec le cumul des exercices antérieurs imputé aux bénéfices non répartis d'ouverture. Et comme il "
                      'réduit le résultat de la filiale, il réduit aussi la quote-part des actionnaires minoritaires.',
 'pndc_resultat': 'Tiré directement de la balance de vérification : produits (crédits) moins charges (débits).',
 'pndc_ecarts': 'Ces écarts appartiennent à la filiale : ils réduisent son résultat pour tous ses actionnaires.',
 'pndc_amont': 'Vente montante : le profit a été dégagé par la filiale, donc il se partage. Une vente descendante serait imputée à 100 % à la mère.',
 'pndc_quote_part': "C'est le montant de l'écriture E19, et la ligne « attribuable aux minoritaires » de l'état des résultats.",
 'pndc_jugement': 'Quelles éliminations réduisent la part des minoritaires ? Celles qui touchent la substance économique de la filiale : '
                  "l'amortissement des écarts de juste valeur et les profits non réalisés sur ses ventes au groupe. Pas celles qui déplacent un coût "
                  "réel d'une entité à l'autre — les intérêts sur le billet de la société mère et les honoraires de gestion facturés au prix du "
                  'marché restent des charges véritables pour la filiale, donc pour ses actionnaires minoritaires. La position se documente une fois '
                  "et s'applique de façon constante.",
 'conversion_1': "Le créditeur intersociétés de 307 692 USD est libellé en dollars canadiens dans l'entente : converti au cours de clôture, il "
                 "redonne exactement 420 000 $ et s'élimine sans résidu. Un solde intersociétés libellé en devise doit toujours se concilier dans la "
                 "monnaie d'origine — tout écart de change qui subsiste est un vrai gain ou une vraie perte, pas une élimination.",
 'conversion_2': "Les bénéfices non répartis convertis ne se recalculent jamais : ils se reportent d'un exercice à l'autre. C'est pourquoi la "
                 'conversion doit être archivée au dossier permanent, pas refaite de mémoire chaque année.',
 'conversion_3': "Si cette filiale était jugée intégrée, stocks et immobilisations seraient convertis aux cours historiques et l'écart traverserait "
                 "l'état des résultats au lieu des capitaux propres."}
