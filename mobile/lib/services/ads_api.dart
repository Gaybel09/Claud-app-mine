import '../core/api_client.dart';
import '../models/ad_view.dart';

abstract class AdsApi {
  Future<AdView> watch({required String adNetwork});

  /// Confirma que o ad_view foi assistido até o fim.
  ///
  /// ATENÇÃO -- CONFIRMAÇÃO TEMPORÁRIA VIA CLIENTE: em produção de
  /// verdade, POST /ads/callback deveria ser chamado só pela verificação
  /// servidor-a-servidor (SSV) real do Google, não pelo próprio app -- ver
  /// o TODO em app/modules/ads/router.py no backend. Chamar isso daqui é
  /// um cliente confirmando a si mesmo (sem assinatura verificável), só
  /// até o SSV real estar implementado. Remova esta chamada (em
  /// MiningController) quando isso acontecer.
  Future<AdView> confirm({required int adViewId, required int userId});
}

class HttpAdsApi implements AdsApi {
  HttpAdsApi(this._client);

  final ApiClient _client;

  @override
  Future<AdView> watch({required String adNetwork}) async {
    final data = await _client.post('/ads/watch', body: {'ad_network': adNetwork});
    return AdView.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<AdView> confirm({required int adViewId, required int userId}) async {
    // POST /ads/callback é server-to-server no backend (rede de anúncios
    // chamando direto) -- não exige o Bearer do usuário.
    final data = await _client.post(
      '/ads/callback',
      body: {'ad_view_id': adViewId, 'user_id': userId, 'status': 'confirmed'},
      auth: false,
    );
    return AdView.fromJson(data as Map<String, dynamic>);
  }
}
