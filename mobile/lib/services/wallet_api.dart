import '../core/api_client.dart';
import '../models/ledger_entry.dart';

abstract class WalletApi {
  Future<double> getBalance();

  Future<Statement> getStatement({int page = 1, int pageSize = 20});
}

class HttpWalletApi implements WalletApi {
  HttpWalletApi(this._client);

  final ApiClient _client;

  @override
  Future<double> getBalance() async {
    final data = await _client.get('/wallet/balance');
    return double.parse((data as Map<String, dynamic>)['balance'].toString());
  }

  @override
  Future<Statement> getStatement({int page = 1, int pageSize = 20}) async {
    final data = await _client.get('/wallet/statement', query: {
      'page': page.toString(),
      'page_size': pageSize.toString(),
    });
    return Statement.fromJson(data as Map<String, dynamic>);
  }
}
