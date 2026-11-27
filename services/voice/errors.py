class VoiceError(Exception):
    code = "VOICE_ERROR"


class VoiceSessionNotFound(VoiceError):
    code = "VOICE_SESSION_NOT_FOUND"


class ResumeVerificationRequired(VoiceError):
    code = "CASE_RESUME_VERIFICATION_REQUIRED"


class UnsafePaymentHandoff(VoiceError):
    code = "UNSAFE_PAYMENT_HANDOFF_REJECTED"


class VoiceStateConflict(VoiceError):
    code = "VOICE_STATE_CONFLICT"


class ResumeChallengeRejected(VoiceError):
    code = "CASE_RESUME_VERIFICATION_REQUIRED"


class TransferDestinationRejected(VoiceError):
    code = "TRANSFER_DESTINATION_REJECTED"


class PaymentHandoffOwnershipRejected(VoiceError):
    code = "PAYMENT_HANDOFF_OWNERSHIP_REJECTED"
