import 'dart:async';

import 'package:google_mobile_ads/google_mobile_ads.dart';

import '../core/ads_config.dart';

/// Carrega e exibe o RewardedAd da tela do cubo (seção 7). Abstraído do
/// plugin `google_mobile_ads` (que exige canais de plataforma reais e não
/// funciona em `flutter test`) para poder ser trocado por uma fake nos
/// testes de widget/controller.
abstract class RewardedAdService {
  /// Carrega e mostra um RewardedAd. Só retorna `true` quando o usuário
  /// assistiu até o fim de verdade (o SDK do Google disparou
  /// `onUserEarnedReward`) -- qualquer outro caso (falha ao carregar,
  /// anúncio fechado antes do fim, erro ao exibir) retorna `false`, sem
  /// nunca liberar o ciclo de mineração.
  Future<bool> loadAndShow();
}

class GoogleMobileAdsRewardedService implements RewardedAdService {
  GoogleMobileAdsRewardedService({String? adUnitId})
      : adUnitId = adUnitId ?? AdsConfig.rewardedAdUnitId;

  final String adUnitId;

  @override
  Future<bool> loadAndShow() {
    final completer = Completer<bool>();

    void complete(bool earnedReward) {
      if (!completer.isCompleted) completer.complete(earnedReward);
    }

    RewardedAd.load(
      adUnitId: adUnitId,
      request: const AdRequest(),
      rewardedAdLoadCallback: RewardedAdLoadCallback(
        onAdLoaded: (ad) {
          ad.fullScreenContentCallback = FullScreenContentCallback(
            // Fechado (skip, voltar, ou fechado normalmente depois do fim)
            // -- se onUserEarnedReward, abaixo, já tiver completado com
            // true, isso é um no-op (completer só aceita o primeiro
            // complete). Se fechou sem ganhar a recompensa, completa false.
            onAdDismissedFullScreenContent: (ad) {
              ad.dispose();
              complete(false);
            },
            onAdFailedToShowFullScreenContent: (ad, error) {
              ad.dispose();
              complete(false);
            },
          );
          ad.show(
            onUserEarnedReward: (ad, reward) {
              // Só aqui o usuário assistiu até o fim de verdade -- é o
              // único caminho que completa com true.
              complete(true);
            },
          );
        },
        onAdFailedToLoad: (error) {
          complete(false);
        },
      ),
    );

    return completer.future;
  }
}
