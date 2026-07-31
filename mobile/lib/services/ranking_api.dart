import '../core/api_client.dart';
import '../models/ranking.dart';

abstract class RankingApi {
  Future<RankingResult> getRanking();
}

class HttpRankingApi implements RankingApi {
  HttpRankingApi(this._client);

  final ApiClient _client;

  @override
  Future<RankingResult> getRanking() async {
    final data = await _client.get('/ranking');
    return RankingResult.fromJson(data as Map<String, dynamic>);
  }
}
