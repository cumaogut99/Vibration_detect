"""
engine_config.py
================
Motor-spesifik bilgiler. Sadece bu dosyayı değiştirerek farklı motora uyarlayın.

Motor: 4-zamanlı, 4-silindirli, redüksiyon dişlili havacılık motoru
Redüksiyon oranı: 0.59:1

NOT — Motor bilgileri (dişli diş sayıları, tam devir aralığı, ateşleme
sırası) henüz teyit edilmemiştir. Doğru değerleri öğrenince bu dosyayı
güncelleyin; kodun başka hiçbir yerine dokunmanız gerekmez.

RPM KAYNAĞI UYARISI
────────────────────
Tachometer sinyali yoktur. DEWESoft'ta yanma orderından (2x) RPM geri
hesaplanmaktadır. Bu yöntem:
  - Yanma anomalisi olan motorda yanlış RPM verir.
  - Tüm order analizinde sistematik kaymaya yol açar.
ÇÖZÜM: Sabit devir noktalarında (2000, 2300, 2500 RPM gibi) ölçüm alın
ve o devri DEWESoft'a manuel sabit değer olarak girin.

SENSÖR KANALI = LOKASYON + EKSEN
──────────────────────────────────
Her kanal bağımsız analiz edilir. Referans da kanal bazındadır.
Toplam 18 kanal: 6 lokasyon × 3 eksen (X, Y, Z)

DOSYA İSİMLENDİRME STANDARDI
──────────────────────────────
<MOTOR_ID>__<YYYYMMDD>__<LOKASYON_KODU>__<EKSEN>__<RUN_ID>.csv

Lokasyon kodları : BLOK_3YAK | BLOK_SOL | MNT_PLAT | DISLI_PER | DISLI_GOV | ALT
Eksenler         : X (shaft ekseni)  |  Y (silindir yönü)  |  Z (yanal)
Örnek            : ENG-042__20260318__DISLI_GOV__X__RUN-001.csv
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


# ---------------------------------------------------------------------------
#  ENUM'LAR
# ---------------------------------------------------------------------------

class FaultCategory(Enum):
    COMBUSTION   = "Combustion"
    MECHANICAL   = "Mechanical"
    BEARING      = "Bearing"
    GEAR         = "Gear"
    IMBALANCE    = "Imbalance"
    MISALIGNMENT = "Misalignment"
    VALVE        = "Valve Train"
    STRUCTURAL   = "Structural Resonance"
    PROPELLER    = "Propeller"
    MOUNT        = "Engine Mount"


class Severity(Enum):
    INFO     = "Info"
    WARNING  = "Warning"
    CRITICAL = "Critical"


# ---------------------------------------------------------------------------
#  VERİ YAPILARI
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SensorChannel:
    """
    Bir ICP sensör kanalı = lokasyon + eksen.
    Her kanal için bağımsız referans ve analiz.
    """
    location_code: str       # Dosya adında kullanılan kısa kod
    location_name: str       # Okunabilir isim
    axis: str                # "X" | "Y" | "Z"
    description: str
    sensitive_to: List[FaultCategory] = field(default_factory=list)
    notes: str = ""

    @property
    def channel_key(self) -> str:
        return f"{self.location_code}_{self.axis}"


@dataclass(frozen=True)
class OrderDefinition:
    """Bir engine order'ının fiziksel anlamı."""
    order: float
    name: str
    source: str
    description: str
    fault_indicators: List[str]   = field(default_factory=list)
    category: FaultCategory       = FaultCategory.MECHANICAL
    # Hangi lokasyonlarda dominant görülür (boşsa hepsinde izlenir)
    dominant_locations: List[str] = field(default_factory=list)
    # Hangi eksende daha belirgin: "X" | "Y" | "Z" | "all"
    dominant_axis: str            = "all"
    # ± fraksiyon olarak frekans arama bandı; None ise OrderExtractor varsayılanı kullanılır.
    # Yakın orderlar (ör. 4.13 vs 4.0, 28.41 vs 29.0) bleed olmasın diye küçültülür.
    tolerance_override: Optional[float] = None


@dataclass(frozen=True)
class FaultSignature:
    """Bir arızanın order örüntüsü."""
    name: str
    category: FaultCategory
    primary_orders: List[float]
    secondary_orders: List[float]
    description: str
    recommendation: str
    amplitude_ratio_threshold: float  = 1.5
    # Hangi lokasyonlarda aranmalı (boşsa hepsinde)
    relevant_locations: List[str]     = field(default_factory=list)
    dominant_axis: str                = "all"


@dataclass(frozen=True)
class FrequencyBand:
    name: str
    low_hz: float
    high_hz: float
    description: str


# ---------------------------------------------------------------------------
#  MOTOR PARAMETRELERİ
#  ⚠ Aşağıdaki değerler henüz teyit edilmemiştir — güncellenecek
# ---------------------------------------------------------------------------

ENGINE_CONFIG = {
    "name":               "4-Stroke 4-Cylinder Piston Aircraft Engine",
    "cylinders":          4,
    "strokes":            4,

    # TODO: Ateşleme sırasını teyit edin (Lycoming/Continental tipik: 1-3-4-2)
    "firing_order":       [1, 3, 4, 2],

    # Redüksiyon dişlisi
    "gear_ratio_reduction":   0.59,
    "gear_ratio_description": "Redüksiyon dişli: pervane mili = krank mili x 0.59",

    # Aksesuar tahrik oranları (krank mili referansı, krank devrine göre order)
    # Sürücü/sürülen oranı (gear ratio) — yağ pompası ve alternatör için diş
    # sayısı bilinmediğinden GMF değil, dönme orderı kullanılır.
    "accessory_drive_orders": {
        "oil_pump":    4.13,   # Yağ pompası dönme orderı (krank x 4.13)
        "alternator":  5.90,   # Alternatör rotor dönme orderı (krank x 5.90)
        # NOT: Vakum pompası ve magneto BU MOTORDA YOKTUR.
        # NOT: Kam mili diş sayısı bilinmediği için ayrı order tanımlanmamıştır.
    },

    # Redüksiyon dişli kutusu (TEYIT EDİLDİ — CAD)
    "reduction_gearbox": {
        "type":              "parallel_with_idler",
        "pinion_teeth":      29,   # Krank tarafı pinyon (sürücü)
        "idler_teeth":       31,   # Ara dişli
        "wheel_teeth":       49,   # Pervane çıkış çarkı
        "primary_gmf_order": 29.0, # Pinyon GMF = 29 x krank
        "sidebands_gmf":     [28.0, 30.0],          # ±1 diş yan bandı
        "sidebands_prop":    [28.41, 29.59],        # ±0.59 prop mili modülasyonu
        "note": (
            "Krank pinyonu 29 dişli olduğu için birincil GMF = 29x krank. "
            "Pervane mili 0.59x krank frekansında döner; bu modülasyon "
            "29 ± 0.59 = (28.41 / 29.59) yan bantlarına yol açar. "
            "± 1 diş yan bantları (28 / 30) dişli profil hatalarını gösterir."
        ),
    },

    # RPM bilgisi
    "nominal_rpm_range":  (1690, 3887),   # Krank mili RPM — teyit bekleniyor
    "max_rpm":            3887,
    "rpm_source":         "COMPUTED_FROM_ORDER",
    "rpm_source_warning": (
        "RPM tachometer YOKTUR. Yanma orderindan (2x) geri hesaplama yapilmaktadir. "
        "Sabit devir noktalarinda olcum alinmasi ve RPM manuel girilmesi onerilir."
    ),
    "recommended_rpm_points": [1690, 2000, 2300, 2500, 3887],
}


# ---------------------------------------------------------------------------
#  SENSÖR KANALLARI — 6 lokasyon × 3 eksen = 18 kanal
# ---------------------------------------------------------------------------

SENSOR_CHANNELS: List[SensorChannel] = [

    # ── Blok üzeri — 3. yatak yakını ──────────────────────────────────────
    SensorChannel(
        location_code="BLOK_3YAK", axis="X",
        location_name="Blok üzeri — 3. yatak yakını",
        description="Krank milinin 3. yatağına yakın. X = shaft ekseni (eksenel/thrust yönü). "
                    "Eksenel yükleme, misalignment, krank thrust yatağı arızalarında yükselir.",
        sensitive_to=[FaultCategory.MISALIGNMENT, FaultCategory.BEARING, FaultCategory.STRUCTURAL],
        notes="Eksenel yön; krank thrust yatağı arızalarında ilk artış burada beklenir.",
    ),
    SensorChannel(
        location_code="BLOK_3YAK", axis="Y",
        location_name="Blok üzeri — 3. yatak yakını",
        description="Y = silindir sırası yönü (dikey). Yanma basıncı ve piston kuvvetleri "
                    "bu yönde dominant. 0.5x, 2x, 4x orderları burada en belirgin.",
        sensitive_to=[FaultCategory.COMBUSTION, FaultCategory.MECHANICAL, FaultCategory.VALVE],
        notes="Yanma kaynaklı orderlar (0.5x, 2x, 4x, 6x) en güçlü bu kanalda görülür.",
    ),
    SensorChannel(
        location_code="BLOK_3YAK", axis="Z",
        location_name="Blok üzeri — 3. yatak yakını",
        description="Z = yanal eksen. Dengesizlik ve krank yanal yüklemesi.",
        sensitive_to=[FaultCategory.IMBALANCE, FaultCategory.BEARING],
    ),

    # ── Blok üzeri — sol mount yakını ─────────────────────────────────────
    SensorChannel(
        location_code="BLOK_SOL", axis="X",
        location_name="Blok üzeri — sol mount yakını",
        description="Sol motor montaj noktası yakını, eksenel yön. "
                    "Mount lastiği bozulmasında 1x ve 2x burada yükselir.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.STRUCTURAL, FaultCategory.MISALIGNMENT],
    ),
    SensorChannel(
        location_code="BLOK_SOL", axis="Y",
        location_name="Blok üzeri — sol mount yakını",
        description="Y = silindir yönü. Mount ile blok arasındaki titreşim iletimi.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.COMBUSTION],
    ),
    SensorChannel(
        location_code="BLOK_SOL", axis="Z",
        location_name="Blok üzeri — sol mount yakını",
        description="Z = yanal. Titreşim izolasyon kaybı.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.IMBALANCE],
    ),

    # ── Mount — platform tarafı ────────────────────────────────────────────
    SensorChannel(
        location_code="MNT_PLAT", axis="X",
        location_name="Mount — platform tarafı",
        description="Motor montaj platformu, eksenel yön. Motorden platforma geçen titreşimi ölçer. "
                    "Referans ile kıyaslamada mount izolasyon etkinliği değerlendirilebilir.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.STRUCTURAL],
        notes="Bu konumdaki genlikler blok sensörlerine göre belirgin şekilde düşük olmalı. "
              "Yüksekse mount degradasyonu düşünülmeli.",
    ),
    SensorChannel(
        location_code="MNT_PLAT", axis="Y",
        location_name="Mount — platform tarafı",
        description="Platform — dikey yön.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.STRUCTURAL],
    ),
    SensorChannel(
        location_code="MNT_PLAT", axis="Z",
        location_name="Mount — platform tarafı",
        description="Platform — yanal yön.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.IMBALANCE],
    ),

    # ── Dişli kutusu — pervane yakını ─────────────────────────────────────
    SensorChannel(
        location_code="DISLI_PER", axis="X",
        location_name="Dişli kutusu — pervane yakını",
        description="Redüksiyon dişli kutusu pervane flanşı tarafı, eksenel. "
                    "Pervane dengesizliği eksenel yönde dominant. "
                    "Tüm orderlar krank mili referanslıdır (0.59 redüksiyon dahil).",
        sensitive_to=[FaultCategory.PROPELLER, FaultCategory.GEAR, FaultCategory.BEARING],
        notes="Pervane 1x = krank 0.59x frekansındadır ancak orderlar krank referanslı "
              "tanımlandığından analizde ek dönüşüm gerekmez.",
    ),
    SensorChannel(
        location_code="DISLI_PER", axis="Y",
        location_name="Dişli kutusu — pervane yakını",
        description="Dişli kutusu pervane tarafı — silindir yönü (dikey). "
                    "Dişli kutusu GMF orderları burada belirgin.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.PROPELLER],
    ),
    SensorChannel(
        location_code="DISLI_PER", axis="Z",
        location_name="Dişli kutusu — pervane yakını",
        description="Dişli kutusu pervane tarafı — yanal.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.BEARING],
    ),

    # ── Dişli kutusu — governor yakını ────────────────────────────────────
    SensorChannel(
        location_code="DISLI_GOV", axis="X",
        location_name="Dişli kutusu — governor yakını",
        description="Redüksiyon dişli kutusu governor tarafı, eksenel. "
                    "Governor sürücü dişlisi GMF'i burada görülür.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.BEARING],
        notes="Governor sürücüsünün kendi dişli sayısı bilinirse ORDER_DEFINITIONS'a ekleyin.",
    ),
    SensorChannel(
        location_code="DISLI_GOV", axis="Y",
        location_name="Dişli kutusu — governor yakını",
        description="Dişli kutusu governor tarafı — dikey.",
        sensitive_to=[FaultCategory.GEAR],
    ),
    SensorChannel(
        location_code="DISLI_GOV", axis="Z",
        location_name="Dişli kutusu — governor yakını",
        description="Dişli kutusu governor tarafı — yanal.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.BEARING],
    ),

    # ── Alternatör üzeri ──────────────────────────────────────────────────
    SensorChannel(
        location_code="ALT", axis="X",
        location_name="Alternatör üzeri",
        description="Alternatör gövdesi, eksenel (shaft yönü). "
                    "Alternatör sürücü kayışı/dişlisi ve rotor dengesizliği.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.IMBALANCE, FaultCategory.BEARING],
        notes="Alternatör rotor frekansı = krank devri x sürücü çarpanı (3x). "
              "3x orderda artış alternatör kayış gerilmesi veya rotor dengesizliğine işaret eder.",
    ),
    SensorChannel(
        location_code="ALT", axis="Y",
        location_name="Alternatör üzeri",
        description="Alternatör — dikey yön.",
        sensitive_to=[FaultCategory.BEARING, FaultCategory.IMBALANCE],
    ),
    SensorChannel(
        location_code="ALT", axis="Z",
        location_name="Alternatör üzeri",
        description="Alternatör — yanal yön.",
        sensitive_to=[FaultCategory.BEARING],
    ),
]

# Hızlı erişim için sözlük: "BLOK_3YAK_X" -> SensorChannel
SENSOR_CHANNEL_MAP: Dict[str, SensorChannel] = {
    ch.channel_key: ch for ch in SENSOR_CHANNELS
}

# Lokasyon kodları listesi (UI için)
LOCATION_CODES: List[str] = list(dict.fromkeys(
    ch.location_code for ch in SENSOR_CHANNELS
))

# Lokasyon adları (UI için)
LOCATION_NAMES: Dict[str, str] = {
    ch.location_code: ch.location_name
    for ch in SENSOR_CHANNELS
}


# ---------------------------------------------------------------------------
#  ORDER TANIMLARI
#  Referans: KRANK MİLİ  (tüm sensörler için ortak)
#
#  4-strok 4-silindir motorun temel orderları:
#    0.5x = Yanma döngüsü fundamentali (4-strok: her 2 tur 1 yanma)
#    1x   = Krank mili dönme frekansı (dengesizlik)
#    2x   = Ateşleme frekansı (4-sil. 4-strok: 2 güç stroğu/tur)
#    4x   = 2. ateşleme harmoniği
#    Nx   = Dişli diş sayısı x krank frekansı
# ---------------------------------------------------------------------------

ORDER_DEFINITIONS: Dict[float, OrderDefinition] = {

    # ── Pervane orderları (krank x 0.59 redüksiyon) ─────────────────────────
    0.59: OrderDefinition(
        order=0.59,
        name="0.59x (Pervane Dönme Frekansı)",
        source="Pervane Mili (Redüksiyon Çıkışı)",
        description=(
            "Pervane mili krank devrinin 0.59'u oranında döner (redüksiyon dişlisi). "
            "Pervane kütle dengesizliği bu orderda dominant görülür. "
            "Pervane flanşı çarpıklığı, kanat hasarı (kuş çarpması, çentik), "
            "pervane göbeği yatağı bozulması burada yükselir."
        ),
        fault_indicators=[
            "Pervane kütle dengesizliği",
            "Pervane kanat hasarı (çentik / kuş çarpması)",
            "Pervane flanşı çarpıklığı",
            "Pervane göbeği yatağı aşınması",
        ],
        category=FaultCategory.PROPELLER,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        dominant_axis="Z",
    ),

    0.5: OrderDefinition(
        order=0.5,
        name="0.5x (Yarım Order)",
        source="Yanma Döngüsü Fundamentali",
        description=(
            "4-strok motorun temel frekansı — her 2 krank turunda 1 yanma döngüsü. "
            "Normal çalışmada düşük genlikli olmalı. Artış misfire veya yanma "
            "düzensizliğine işaret eder."
        ),
        fault_indicators=["Ateşleme arızası (misfire)", "Düzensiz yanma", "Ateşleme zamanlaması hatası"],
        category=FaultCategory.COMBUSTION,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    1.0: OrderDefinition(
        order=1.0,
        name="1x (Krank Dönme Frekansı)",
        source="Krank Mili Rotasyonu",
        description=(
            "Krank milinin temel dönme frekansı. Krank ucundaki kütle dengesizliği "
            "(volan, kavrama), büküleşmiş krank veya iç redüksiyon dişlisi tarafındaki "
            "dengesizlik burada görülür. Pervane dengesizliği 0.59x'te yer alır; bunu "
            "1x ile karıştırmamak gerekir."
        ),
        fault_indicators=[
            "Krank ucu (volan / kavrama) dengesizliği",
            "Büküleşmiş krank mili",
            "Redüksiyon giriş tarafı dengesizliği",
        ],
        category=FaultCategory.IMBALANCE,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Z",
    ),

    1.5: OrderDefinition(
        order=1.5,
        name="1.5x",
        source="Yanma + Rotasyon Etkileşimi",
        description=(
            "Yarım order ve birinci order arasındaki intermodülasyon. "
            "Silindir-silindir yanma varyasyonu veya kombine dengesizlik + yanma sorununda görülür."
        ),
        fault_indicators=["Silindir-silindir yanma farkı", "Kombine dengesizlik+yanma"],
        category=FaultCategory.COMBUSTION,
        dominant_axis="Y",
    ),

    1.77: OrderDefinition(
        order=1.77,
        name="1.77x (Pervane 3-Kanat BPF)",
        source="Pervane Kanat Geçiş Frekansı (3 kanat)",
        description=(
            "3 kanatlı pervane için kanat geçiş frekansı (BPF = 3 x 0.59 = 1.77x). "
            "Pervane kanat profil aşınması, kanat açı simetrisizliği veya "
            "aerodinamik dengesizlikte yükselir. 0.59x'le birlikte değerlendirilmelidir."
        ),
        fault_indicators=[
            "Pervane kanat profil aşınması",
            "Kanatlar arası açı simetrisizliği",
            "Pervane aerodinamik dengesizliği",
        ],
        category=FaultCategory.PROPELLER,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        dominant_axis="Z",
        # 1.77 vs 2.0 arası ~%13; default tolerans 5% ile karışmaz ama biraz daraltıyoruz.
        tolerance_override=0.03,
    ),

    2.0: OrderDefinition(
        order=2.0,
        name="2x (Ateşleme Frekansı)",
        source="Ateşleme Frekansı",
        description=(
            "4-silindirli 4-strok motorun birincil ateşleme frekansı "
            "(tur başına 2 güç stroğu). RPM'in yanma orderından geri hesaplandığı "
            "bu projede 2x genliği RPM hesaplamasında referans alınmaktadır. "
            "Aşırı artış yanma basıncı varyasyonu veya ikincil dengesizliğe işaret eder."
        ),
        fault_indicators=[
            "Yanma basıncı varyasyonu",
            "İkincil dengesizlik (piston kuvvetleri)",
            "Piston yanal kuvveti",
        ],
        category=FaultCategory.COMBUSTION,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
        tolerance_override=0.03,
    ),

    3.0: OrderDefinition(
        order=3.0,
        name="3x (Krank Torsiyonel / Yapısal)",
        source="Krank Torsiyonel Rezonansı / Yapısal",
        description=(
            "Krank mili torsiyonel rezonansı veya yapısal rezonans harmoniği. "
            "Belirli RPM noktalarında kilitli görülürse torsiyonel mod uyarılmıştır."
        ),
        fault_indicators=[
            "Krank torsiyonel rezonansı",
            "Yapısal rezonans (mount / blok)",
        ],
        category=FaultCategory.STRUCTURAL,
        dominant_axis="Y",
    ),

    4.0: OrderDefinition(
        order=4.0,
        name="4x (2. Ateşleme Harmoniği)",
        source="Ateşleme Frekansı 2. Harmoniği",
        description=(
            "Ateşleme frekansının 2. harmoniği; aynı zamanda tur başına 4 piston stroğu. "
            "Valf treni sorunları, piston-silindir etkileşimi."
        ),
        fault_indicators=["Valf treni sorunu", "Piston-silindir etkileşimi", "Yanma harmoniği"],
        category=FaultCategory.VALVE,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
        # 4.0 vs 4.13 ~%3.2; tolerans 0.012 ~ %1.2 ile ayrıştırılır.
        tolerance_override=0.012,
    ),

    4.13: OrderDefinition(
        order=4.13,
        name="4.13x (Yağ Pompası Dönme Orderı)",
        source="Yağ Pompası Sürücü Oranı",
        description=(
            "Yağ pompası rotor dönme orderı (krank x 4.13). Pompa diş sayısı "
            "bilinmediği için GMF değil dönme frekansı izlenir. Artış yağ pompası "
            "kavitasyonu, basınç pulsasyonu veya pompa yatağı aşınmasına işaret eder."
        ),
        fault_indicators=[
            "Yağ pompası kavitasyonu",
            "Yağ basıncı pulsasyonu",
            "Yağ pompası yatağı aşınması",
        ],
        category=FaultCategory.MECHANICAL,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        # 4.0 ve 5.9'a yakın; sıkı tolerans gerekli.
        tolerance_override=0.012,
    ),

    5.9: OrderDefinition(
        order=5.9,
        name="5.9x (Alternatör Dönme Orderı)",
        source="Alternatör Sürücü Oranı",
        description=(
            "Alternatör rotor dönme orderı (krank x 5.90). Rotor dengesizliği, "
            "kayış gerginlik kaybı veya alternatör yatak aşınmasında yükselir. "
            "6x (valf treni) ile karışmaması için sıkı toleransla aranır."
        ),
        fault_indicators=[
            "Alternatör rotor dengesizliği",
            "Alternatör yatak aşınması",
            "Sürücü kayışı gerginlik kaybı",
        ],
        category=FaultCategory.IMBALANCE,
        dominant_locations=["ALT"],
        dominant_axis="X",
        # 5.9 vs 6.0 sadece %1.7; çok sıkı tolerans.
        tolerance_override=0.008,
    ),

    6.0: OrderDefinition(
        order=6.0,
        name="6x (Valf Treni)",
        source="Valf Treni",
        description=(
            "4-silindirli 4-strok motorda valf olayları frekansı. "
            "Yorulmuş valf yayı, aşınmış rocker arm veya kam lobunda aşınma."
        ),
        fault_indicators=["Valf yayı yorulması", "Rocker arm aşınması", "Kam lobu aşınması"],
        category=FaultCategory.VALVE,
        dominant_axis="Y",
        tolerance_override=0.008,
    ),

    8.0: OrderDefinition(
        order=8.0,
        name="8x (4. Ateşleme Harmoniği)",
        source="Ateşleme 4. Harmoniği / Piston",
        description="Piston vuruşu (piston slap) ve silindir iç yüzey etkileşimleri.",
        fault_indicators=["Piston vuruşu (slap)", "Segment aşınması", "Silindir yuvarlaksal bozulma"],
        category=FaultCategory.MECHANICAL,
        dominant_axis="Y",
    ),

    # ── Dişli kutusu — pinyon GMF ve yan bantları ───────────────────────────
    28.0: OrderDefinition(
        order=28.0,
        name="28x (Dişli Kutusu GMF − 1 diş)",
        source="Dişli Kutusu Diş Profili Modülasyonu",
        description=(
            "Pinyon GMF'inin (29x) bir diş aşağı yan bandı. Dişli profilinde "
            "bireysel diş hatası (çatlak, ufalanma) varsa 29x ile birlikte 28x ve 30x "
            "yan bantları yükselir."
        ),
        fault_indicators=[
            "Dişli profili hatası (tek diş çatlak/aşınma)",
            "Dişli yüzey ufalanması (spalling)",
        ],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        tolerance_override=0.012,
    ),

    28.41: OrderDefinition(
        order=28.41,
        name="28.41x (Dişli Kutusu GMF − Pervane Yan Bandı)",
        source="Dişli Kutusu — Pervane Mili Modülasyonu",
        description=(
            "Pinyon GMF (29x) ± pervane mili dönme frekansı (0.59x) = 28.41x ve 29.59x. "
            "Bu yan bantlar pervane tarafı yük modülasyonu veya çıkış çarkı (49 dişli) "
            "kaynaklı eksantrisitede görülür. 28.41x ile 29.0x arası sadece 0.59 order; "
            "bleed olmaması için çok sıkı tolerans uygulanır."
        ),
        fault_indicators=[
            "Pervane mili eksantrisitesi",
            "Çıkış çarkı (49 dişli) montaj hatası",
            "Pervane yük modülasyonu",
        ],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        # 28.41 ile 29.0 arası %2.0; tol = %0.5 → 0.14 order halfwidth.
        tolerance_override=0.005,
    ),

    29.0: OrderDefinition(
        order=29.0,
        name="29x (Dişli Kutusu Pinyon GMF)",
        source="Redüksiyon Dişli Kutusu — Pinyon Sürücü",
        description=(
            "Birincil dişli kutusu GMF: 29 dişli krank pinyonu x krank devri. "
            "CAD'den teyit edilen dişli düzeni: 29 dişli pinyon × 31 dişli ara dişli × "
            "49 dişli çıkış çarkı (paralel mil, idler ile). Dişli ağzı aşınması, "
            "diş profili hatası ve yatak boşluğu burada görülür."
        ),
        fault_indicators=[
            "Dişli ağzı aşınması (pinyon)",
            "Dişli yüzey çukurlaşması (pitting)",
            "Pinyon mili yatağı aşınması",
            "Sürücü dişli boşluğu artışı",
        ],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        dominant_axis="all",
        # 28.41/29/29.59 üçlüsünü ayırt etmek için sıkı tolerans.
        tolerance_override=0.005,
    ),

    29.59: OrderDefinition(
        order=29.59,
        name="29.59x (Dişli Kutusu GMF + Pervane Yan Bandı)",
        source="Dişli Kutusu — Pervane Mili Modülasyonu",
        description=(
            "Pinyon GMF (29x) + pervane mili dönme frekansı (0.59x). 28.41 ile birlikte "
            "değerlendirilir; her ikisinin yükselişi pervane tarafı eksantrisite ya da "
            "çıkış çarkı montaj hatasını gösterir."
        ),
        fault_indicators=[
            "Pervane mili eksantrisitesi",
            "Çıkış çarkı (49 dişli) montaj hatası",
        ],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        tolerance_override=0.005,
    ),

    30.0: OrderDefinition(
        order=30.0,
        name="30x (Dişli Kutusu GMF + 1 diş)",
        source="Dişli Kutusu Diş Profili Modülasyonu",
        description=(
            "Pinyon GMF'inin (29x) bir diş yukarı yan bandı. 28x ile birlikte "
            "değerlendirilir; ikisi birden yükseliyorsa diş profilinde bireysel hata "
            "(çatlak, ufalanma) muhtemeldir."
        ),
        fault_indicators=[
            "Dişli profili hatası (tek diş)",
            "Dişli yüzey ufalanması",
        ],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        tolerance_override=0.012,
    ),

    58.0: OrderDefinition(
        order=58.0,
        name="58x (Dişli Kutusu GMF 2. Harmoniği)",
        source="Pinyon GMF 2. Harmoniği",
        description=(
            "Dişli kutusu GMF'inin 2. harmoniği (2 x 29x). 29x ile birlikte yükseliyorsa "
            "dişli aşınması ilerliyor demektir."
        ),
        fault_indicators=["İleri düzey dişli aşınması", "Diş profili hasarı"],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
    ),

    87.0: OrderDefinition(
        order=87.0,
        name="87x (Dişli Kutusu GMF 3. Harmoniği)",
        source="Pinyon GMF 3. Harmoniği",
        description="Dişli kutusu GMF 3. harmoniği (3 x 29x). Ciddi dişli hasarı göstergesi.",
        fault_indicators=["Ağır dişli hasarı", "Diş soyulması (spalling)"],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
    ),
}


# ---------------------------------------------------------------------------
#  ARIZA İMZALARI
# ---------------------------------------------------------------------------

FAULT_SIGNATURES: List[FaultSignature] = [

    FaultSignature(
        name="Pervane Kütle Dengesizliği",
        category=FaultCategory.PROPELLER,
        primary_orders=[0.59],
        secondary_orders=[1.77],
        description=(
            "0.59x order pervane mili dönme orderıdır; artışı pervane kütle "
            "dengesizliğini (kanat hasarı, flanş çarpıklığı, göbek montaj hatası) "
            "gösterir. 1.77x (3-kanat BPF) ile birlikte yükselmesi aerodinamik "
            "dengesizliğe işaret eder."
        ),
        recommendation=(
            "Pervaneyi dengeleyin (statik + dinamik). Kanat profilini çentik / "
            "kuş çarpması açısından inceleyin. Pervane göbeği ve flanş çarpıklığını "
            "ölçün. DISLI_PER ve DISLI_GOV sensörlerine odaklanın."
        ),
        amplitude_ratio_threshold=1.5,
        relevant_locations=["DISLI_PER", "DISLI_GOV"],
        dominant_axis="Z",
    ),

    FaultSignature(
        name="Pervane Kanat / Aerodinamik Anomalisi",
        category=FaultCategory.PROPELLER,
        primary_orders=[1.77],
        secondary_orders=[0.59],
        description=(
            "Kanat geçiş frekansının (1.77x = 3 x 0.59) baskın artışı kanatlar "
            "arası açı simetrisizliği veya kanat profili aşınmasını gösterir."
        ),
        recommendation=(
            "Kanat açılarını ve profil bütünlüğünü kontrol edin. Track-and-balance "
            "prosedürü uygulayın."
        ),
        amplitude_ratio_threshold=1.5,
        relevant_locations=["DISLI_PER", "DISLI_GOV"],
        dominant_axis="Z",
    ),

    FaultSignature(
        name="Krank Mili Dengesizliği",
        category=FaultCategory.IMBALANCE,
        primary_orders=[1.0],
        secondary_orders=[2.0],
        description=(
            "1x order krank ucundaki (volan / kavrama / redüksiyon giriş tarafı) "
            "kütle dengesizliğini veya bükük krank milini gösterir. Pervane "
            "dengesizliğiyle (0.59x) karıştırılmamalıdır."
        ),
        recommendation=(
            "Krank ucu komponentlerini (volan, kavrama, redüksiyon giriş "
            "tahriki) dengeleyin. Krank eksenel sapmasını ölçün."
        ),
        amplitude_ratio_threshold=1.5,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Z",
    ),

    FaultSignature(
        name="Mil Hizasızlığı (Misalignment)",
        category=FaultCategory.MISALIGNMENT,
        primary_orders=[1.0, 2.0],
        secondary_orders=[3.0],
        description=(
            "Yüksek 1x ve 2x order eksenel bileşenlerle birlikte angular veya "
            "paralel hizasızlığa işaret eder."
        ),
        recommendation=(
            "Motor montaj hizasını kontrol edin. Krank mili eksenel boşluğunu ölçün. "
            "Pervane flanşı çarpıklığını kontrol edin."
        ),
        amplitude_ratio_threshold=1.4,
        dominant_axis="X",
    ),

    FaultSignature(
        name="Yanma Anomalisi / Ateşleme Arızası",
        category=FaultCategory.COMBUSTION,
        primary_orders=[0.5, 2.0],
        secondary_orders=[1.5, 4.0],
        description=(
            "0.5x (yarım order) artışı 4-strok motorun en önemli yanma göstergesidir. "
            "Normal çalışmada düşük olmalıdır; artış misfire veya düzensiz yanmayı gösterir."
        ),
        recommendation=(
            "Bujileri kontrol edin ve gerekirse değiştirin. Ateşleme zamanlamasını "
            "kontrol edin. Yakıt enjektör debilerini dengeleyin. Her silindirde "
            "kompresyon testi yapın."
        ),
        amplitude_ratio_threshold=1.6,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    FaultSignature(
        name="Valf Treni Aşınması",
        category=FaultCategory.VALVE,
        primary_orders=[4.0, 6.0],
        secondary_orders=[8.0],
        description=(
            "4x ve 6x order artışı aşınmış rocker arm, zayıf valf yayı veya "
            "kam lobu aşınmasına işaret eder."
        ),
        recommendation=(
            "Rocker arm boşluklarını ölçün. Valf yayı kuvvetlerini kontrol edin. "
            "Kam lobu profillerini inceleyin."
        ),
        amplitude_ratio_threshold=1.5,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    FaultSignature(
        name="Dişli Kutusu Aşınması",
        category=FaultCategory.GEAR,
        primary_orders=[29.0],
        secondary_orders=[28.0, 30.0, 28.41, 29.59, 58.0, 87.0],
        description=(
            "29x birincil pinyon GMF'idir (29 dişli krank pinyonu). Artışı dişli "
            "ağzı aşınması, profil bozulması veya yatak boşluğu artışını gösterir. "
            "± 1 diş yan bantları (28 / 30) tek diş hatasını; ± 0.59 pervane "
            "modülasyonu yan bantları (28.41 / 29.59) çıkış çarkı / pervane mili "
            "eksantrisitesini gösterir. 58 ve 87 harmonikleri hasarın ilerlediğini "
            "gösterir."
        ),
        recommendation=(
            "Redüksiyon dişli kutusunu söküp pinyon, ara dişli ve çıkış çarkını "
            "çukurlaşma / soyulma / boşluk açısından inceleyin. Yatak boşluklarını "
            "ölçün. Yan bantları yüksekse pervane mili eksantrisitesi ve çıkış "
            "çarkı montajını kontrol edin."
        ),
        amplitude_ratio_threshold=1.4,
        relevant_locations=["DISLI_PER", "DISLI_GOV"],
    ),

    FaultSignature(
        name="Yağ Pompası Anomalisi",
        category=FaultCategory.MECHANICAL,
        primary_orders=[4.13],
        secondary_orders=[],
        description=(
            "4.13x yağ pompası rotor dönme orderıdır. Artışı pompa kavitasyonu, "
            "basınç pulsasyonu veya yatak aşınmasına işaret eder."
        ),
        recommendation=(
            "Yağ basıncını farklı RPM noktalarında ölçün. Pompa gövde ve yatak "
            "boşluklarını kontrol edin. Yağ filtresinde metal partikül kontrolü yapın."
        ),
        amplitude_ratio_threshold=1.4,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
    ),

    FaultSignature(
        name="Alternatör Anomalisi",
        category=FaultCategory.IMBALANCE,
        primary_orders=[5.9],
        secondary_orders=[],
        description=(
            "5.9x alternatör rotor dönme orderıdır. Artışı rotor dengesizliği, "
            "yatak aşınması veya kayış gerginlik kaybını gösterir."
        ),
        recommendation=(
            "Alternatör kayış gerginliğini kontrol edin. Rotor yataklarını dinleyin. "
            "Alternatörü yerinden çıkarıp dengelemek gerekebilir."
        ),
        amplitude_ratio_threshold=1.4,
        relevant_locations=["ALT"],
        dominant_axis="X",
    ),

    FaultSignature(
        name="Piston Vuruşu / Segment Aşınması",
        category=FaultCategory.MECHANICAL,
        primary_orders=[8.0],
        secondary_orders=[4.0],
        description=(
            "8x order artışı ve geniş bantlı gürültü artışı piston-silindir boşluğu "
            "sorununa işaret eder."
        ),
        recommendation=(
            "Tüm silindirlerde kompresyon ve diferansiyel basınç testi yapın. "
            "Silindir içini borescope ile inceleyin."
        ),
        amplitude_ratio_threshold=1.6,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    FaultSignature(
        name="Motor Montaj (Mount) Bozulması",
        category=FaultCategory.MOUNT,
        primary_orders=[1.0, 2.0],
        secondary_orders=[0.5],
        description=(
            "Düşük frekanslarda geniş bant artışı ve mount sensöründe (MNT_PLAT) "
            "yüksek genlik, montaj lastiğinin bozulduğuna işaret eder."
        ),
        recommendation=(
            "Tüm motor montaj burçlarını çatlak, sertleşme ve çökme açısından inceleyin. "
            "Montaj cıvata tork değerlerini kontrol edin."
        ),
        amplitude_ratio_threshold=1.4,
        relevant_locations=["MNT_PLAT", "BLOK_SOL"],
    ),

    FaultSignature(
        name="Krank Mili Torsiyonel Rezonansı",
        category=FaultCategory.STRUCTURAL,
        primary_orders=[3.0, 6.0],
        secondary_orders=[1.5],
        description=(
            "Belirli RPM noktalarında 3x ve 6x order kilitli rezonans krank mili "
            "torsiyonel titreşimine işaret eder."
        ),
        recommendation=(
            "Vibrasyon vs RPM haritasını inceleyerek rezonans noktalarını belirleyin. "
            "Krank milini, pervane vantuzunu ve dinamik sönümleyiciyi (varsa) kontrol edin."
        ),
        amplitude_ratio_threshold=1.7,
    ),
]


# ---------------------------------------------------------------------------
#  FREKANS BANTLARI  (mutlak Hz — sabit devir veya referans analizi için)
# ---------------------------------------------------------------------------

FREQUENCY_BANDS: List[FrequencyBand] = [
    FrequencyBand("Alt-senkron",         0.0,    25.0,
                  "Mil frekansı altı — yapısal, instabilite"),
    FrequencyBand("Mil Fundamentali",   25.0,    55.0,
                  "Krank mili dönme aralığı (1800-2700 RPM)"),
    FrequencyBand("Ateşleme Frekansı",  55.0,   110.0,
                  "Yanma / ateşleme harmonikleri"),
    FrequencyBand("Valf Treni",        100.0,   250.0,
                  "Valf treni ve kam mili aktivitesi"),
    FrequencyBand("Dişli Ağzı Düşük",  250.0,   800.0,
                  "Düşük dişli ağzı frekansları (yağ pompası, kam mili)"),
    FrequencyBand("Dişli Ağzı Yüksek", 800.0,  2500.0,
                  "Yüksek dişli ağzı frekansları (pinyon GMF: ~870-1300 Hz @ 1800-2700 RPM)"),
    FrequencyBand("Yüksek Frekans",   2500.0, 10000.0,
                  "Yapısal rezonanslar, yatak arıza frekansları"),
]


# ---------------------------------------------------------------------------
#  UYARI EŞİKLERİ  (referansa göre genlik oranı)
# ---------------------------------------------------------------------------

ALERT_THRESHOLDS = {
    Severity.WARNING:  1.5,   # Referansın %50 üzeri
    Severity.CRITICAL: 2.5,   # Referansın %150 üzeri
}

# Her zaman izlenecek orderlar — tüm motor / aksesuar gözlemleri için temel set
MANDATORY_MONITOR_ORDERS = [
    0.5, 0.59, 1.0, 1.77, 2.0, 4.0, 4.13, 5.9, 6.0, 29.0,
]

# Hassas orderlar — daha düşük eşikle alarm verir (kritik dişli + pervane)
SENSITIVE_ORDERS = [
    0.59, 1.77,                 # Pervane fundamental + BPF
    4.13,                       # Yağ pompası
    5.9,                        # Alternatör
    28.0, 28.41, 29.0, 29.59, 30.0,  # Dişli kutusu GMF + yan bantları
    58.0, 87.0,                 # GMF harmonikleri
]
SENSITIVE_THRESHOLD_MULTIPLIER = 0.8   # Normal eşiğin %80'i
