import 'dart:io' show Platform;

/// Configuração do Google Mobile Ads (SDK `google_mobile_ads`) para o
/// RewardedAd da tela do cubo (seção 7).
///
/// O App ID (identifica a conta AdMob do app) fica configurado nos
/// manifests nativos -- ver android/app/src/main/AndroidManifest.xml
/// (`com.google.android.gms.ads.APPLICATION_ID`) e ios/Runner/Info.plist
/// (`GADApplicationIdentifier`), o SDK lê de lá, não daqui. É seguro deixar
/// sempre o App ID real (ca-app-pub-9407999187872272~5109632072) mesmo em
/// desenvolvimento: quem determina se o conteúdo servido é de teste ou de
/// verdade é o Ad Unit ID, não o App ID.
///
/// Por isso o Ad Unit ID por padrão usa os IDs de teste OFICIAIS do Google
/// (https://developers.google.com/admob/flutter/test-ads) -- sempre servem
/// anúncio de teste, nunca real, não importa a conta/dispositivo -- para
/// não arriscar a conta AdMob real enquanto o app ainda está em
/// desenvolvimento. Para usar o Ad Unit ID real do bloco premiado do
/// CubeMine Pix (ca-app-pub-9407999187872272/9926844486) em produção de
/// verdade:
///   flutter build apk --dart-define=ADS_USE_TEST_AD_UNITS=false
class AdsConfig {
  static const useTestAdUnits = bool.fromEnvironment(
    'ADS_USE_TEST_AD_UNITS',
    defaultValue: true,
  );

  /// Ad Unit ID real do bloco premiado (RewardedAd) do CubeMine Pix.
  static const _realRewardedAdUnitId = 'ca-app-pub-9407999187872272/9926844486';

  // IDs de teste oficiais do Google -- iguais pra qualquer app/conta,
  // documentados em https://developers.google.com/admob/flutter/test-ads.
  static const _testRewardedAdUnitIdAndroid = 'ca-app-pub-3940256099942544/5224354917';
  static const _testRewardedAdUnitIdIOS = 'ca-app-pub-3940256099942544/1712485313';

  static String get rewardedAdUnitId {
    if (!useTestAdUnits) return _realRewardedAdUnitId;
    return Platform.isIOS ? _testRewardedAdUnitIdIOS : _testRewardedAdUnitIdAndroid;
  }
}
