import '../core/api_client.dart';
import '../models/ad_view.dart';

abstract class AdsApi {
  Future<AdView> watch({required String adNetwork});
}

class HttpAdsApi implements AdsApi {
  HttpAdsApi(this._client);

  final ApiClient _client;

  @override
  Future<AdView> watch({required String adNetwork}) async {
    final data = await _client.post('/ads/watch', body: {'ad_network': adNetwork});
    return AdView.fromJson(data as Map<String, dynamic>);
  }
}
