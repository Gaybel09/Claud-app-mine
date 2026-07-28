import '../core/api_client.dart';
import '../models/withdrawal.dart';

abstract class PixApi {
  /// pixKey omitido usa a chave já cadastrada no perfil do usuário (ver
  /// backend PixWithdrawRequest.pix_key) -- só precisa ser enviada aqui
  /// quando o usuário ainda não tem uma cadastrada.
  Future<Withdrawal> withdraw({
    required double amount,
    String? pixKey,
    required String idempotencyKey,
  });

  Future<List<Withdrawal>> listWithdrawals();
}

class HttpPixApi implements PixApi {
  HttpPixApi(this._client);

  final ApiClient _client;

  @override
  Future<Withdrawal> withdraw({
    required double amount,
    String? pixKey,
    required String idempotencyKey,
  }) async {
    final data = await _client.post(
      '/pix/withdraw',
      // Formatado como string com 2 casas -- evita o backend (Decimal)
      // receber um float binário impreciso (ex: 40.1 chegando como
      // 40.099999999999994) que um número JSON puro poderia carregar.
      body: {
        'amount': amount.toStringAsFixed(2),
        'pix_key': ?pixKey,
      },
      extraHeaders: {'Idempotency-Key': idempotencyKey},
    );
    return Withdrawal.fromJson(data as Map<String, dynamic>);
  }

  @override
  Future<List<Withdrawal>> listWithdrawals() async {
    final data = await _client.get('/pix/withdrawals');
    return (data as List)
        .map((e) => Withdrawal.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}
