class AppUser {
  const AppUser({
    required this.id,
    required this.email,
    required this.phone,
    required this.pixKey,
    required this.kycStatus,
    required this.createdAt,
    required this.isBlocked,
    this.nickname,
    this.countryCode,
    this.stateCode,
  });

  final int id;
  final String email;
  final String? phone;
  final String? pixKey;
  final String kycStatus;
  final DateTime createdAt;
  final bool isBlocked;

  /// Exibido no ranking (ver RankingScreen) no lugar do email -- null até o
  /// usuário definir um via PATCH /auth/nickname.
  final String? nickname;
  final String? countryCode;
  final String? stateCode;

  factory AppUser.fromJson(Map<String, dynamic> json) {
    return AppUser(
      id: json['id'] as int,
      email: json['email'] as String,
      phone: json['phone'] as String?,
      pixKey: json['pix_key'] as String?,
      kycStatus: json['kyc_status'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
      isBlocked: json['is_blocked'] as bool,
      nickname: json['nickname'] as String?,
      countryCode: json['country_code'] as String?,
      stateCode: json['state_code'] as String?,
    );
  }
}
