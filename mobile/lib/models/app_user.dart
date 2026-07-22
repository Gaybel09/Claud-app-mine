class AppUser {
  const AppUser({
    required this.id,
    required this.email,
    required this.phone,
    required this.pixKey,
    required this.kycStatus,
    required this.createdAt,
    required this.isBlocked,
  });

  final int id;
  final String email;
  final String? phone;
  final String? pixKey;
  final String kycStatus;
  final DateTime createdAt;
  final bool isBlocked;

  factory AppUser.fromJson(Map<String, dynamic> json) {
    return AppUser(
      id: json['id'] as int,
      email: json['email'] as String,
      phone: json['phone'] as String?,
      pixKey: json['pix_key'] as String?,
      kycStatus: json['kyc_status'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
      isBlocked: json['is_blocked'] as bool,
    );
  }
}
