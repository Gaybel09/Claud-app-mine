class Withdrawal {
  const Withdrawal({
    required this.id,
    required this.userId,
    required this.amount,
    required this.pixKey,
    required this.status,
    required this.idempotencyKey,
    required this.createdAt,
  });

  final int id;
  final int userId;
  final double amount;
  final String pixKey;
  final String status;
  final String idempotencyKey;
  final DateTime createdAt;

  factory Withdrawal.fromJson(Map<String, dynamic> json) {
    return Withdrawal(
      id: json['id'] as int,
      userId: json['user_id'] as int,
      amount: double.parse(json['amount'].toString()),
      pixKey: json['pix_key'] as String,
      status: json['status'] as String,
      idempotencyKey: json['idempotency_key'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}
