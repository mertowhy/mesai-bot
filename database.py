import os
import logging
from pymongo import MongoClient

logger = logging.getLogger("sahp_bot")

class Database:
    def __init__(self, uri: str = None):
        if not uri:
            # Fallback or default
            uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/sahp_bot")
        
        self.client = MongoClient(uri)
        # database name is sahp_bot
        self.db = self.client["sahp_bot"]
        
        self.sessions = self.db["mesai_sessions"]
        self.totals = self.db["mesai_totals"]
        self.mazerets = self.db["mazerets"]
        
        self._init_db()

    def _init_db(self):
        # Create indexes for performance
        try:
            self.sessions.create_index([("user_id", 1), ("leave_time", 1)])
            self.totals.create_index([("user_id", 1)], unique=True)
            self.mazerets.create_index([("user_id", 1)])
            logger.info("MongoDB indexes created successfully.")
        except Exception as e:
            logger.error(f"Failed to create MongoDB indexes: {e}")

    def start_session(self, user_id: str, username: str, join_time: int):
        # Clean up any orphaned sessions for this user before starting a new one
        try:
            orphaned = self.sessions.find({"user_id": user_id, "leave_time": None})
            for doc in orphaned:
                self.sessions.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"leave_time": doc["join_time"], "duration": 0}}
                )
                logger.warning(f"Orphaned session closed in MongoDB for user {username} ({user_id})")
        except Exception as e:
            logger.error(f"Error during cleaning orphaned sessions: {e}")

        # Insert new active session
        try:
            self.sessions.insert_one({
                "user_id": user_id,
                "username": username,
                "join_time": join_time,
                "leave_time": None,
                "duration": None
            })
            logger.info(f"Mesai session started for {username} ({user_id}) at {join_time}")
        except Exception as e:
            logger.error(f"Failed to start session in MongoDB: {e}")

    def end_session(self, user_id: str, leave_time: int) -> int:
        try:
            # Find active session
            doc = self.sessions.find_one({"user_id": user_id, "leave_time": None})
            if not doc:
                logger.warning(f"No active session found to end for user ID {user_id}")
                return 0
                
            join_time = doc["join_time"]
            username = doc["username"]
            duration = max(0, leave_time - join_time)
            
            # Update session
            self.sessions.update_one(
                {"_id": doc["_id"]},
                {"$set": {"leave_time": leave_time, "duration": duration}}
            )
            
            # Update or Insert total time (upsert)
            self.totals.update_one(
                {"user_id": user_id},
                {
                    "$set": {"username": username},
                    "$inc": {"total_duration": duration}
                },
                upsert=True
            )
            
            logger.info(f"Mesai session ended for {username} ({user_id}). Duration: {duration}s")
            return duration
        except Exception as e:
            logger.error(f"Failed to end session in MongoDB: {e}")
            return 0

    def get_total_time(self, user_id: str) -> int:
        try:
            row = self.totals.find_one({"user_id": user_id})
            return row["total_duration"] if row else 0
        except Exception as e:
            logger.error(f"Failed to fetch total time from MongoDB: {e}")
            return 0

    def get_all_totals(self) -> list:
        try:
            cursor = self.totals.find().sort("total_duration", -1)
            results = []
            for doc in cursor:
                results.append({
                    "user_id": doc["user_id"],
                    "username": doc["username"],
                    "total_duration": doc["total_duration"]
                })
            return results
        except Exception as e:
            logger.error(f"Failed to fetch all totals from MongoDB: {e}")
            return []

    def reset_mesai(self, user_id: str = None) -> bool:
        try:
            if user_id:
                self.sessions.delete_many({"user_id": user_id})
                self.totals.delete_many({"user_id": user_id})
            else:
                self.sessions.delete_many({})
                self.totals.delete_many({})
            logger.info(f"Mesai data reset completed in MongoDB. Target user: {user_id or 'ALL'}")
            return True
        except Exception as e:
            logger.error(f"Failed to reset mesai in MongoDB: {e}")
            return False

    def clear_active_sessions(self, current_time: int):
        """
        On bot start, close any active sessions left open due to bot crash/shutdown.
        Sets their leave_time to join_time (0 duration) to avoid generating artificial hours.
        """
        try:
            active_sessions = self.sessions.find({"leave_time": None})
            count = 0
            for doc in active_sessions:
                self.sessions.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"leave_time": doc["join_time"], "duration": 0}}
                )
                count += 1
            if count > 0:
                logger.info(f"Closed {count} interrupted sessions in MongoDB with 0 duration.")
        except Exception as e:
            logger.error(f"Failed to clear active sessions in MongoDB: {e}")

    def get_weekly_time(self, user_id: str) -> int:
        try:
            import time
            seven_days_ago = int(time.time()) - (7 * 24 * 60 * 60)
            pipeline = [
                {
                    "$match": {
                        "user_id": user_id, 
                        "join_time": {"$gte": seven_days_ago}, 
                        "leave_time": {"$ne": None}
                    }
                },
                {
                    "$group": {
                        "_id": None, 
                        "total": {"$sum": "$duration"}
                    }
                }
            ]
            result = list(self.sessions.aggregate(pipeline))
            return result[0]["total"] if result else 0
        except Exception as e:
            logger.error(f"Failed to fetch weekly time from MongoDB: {e}")
            return 0

    def get_all_weekly_totals(self) -> list:
        try:
            import time
            seven_days_ago = int(time.time()) - (7 * 24 * 60 * 60)
            pipeline = [
                {
                    "$match": {
                        "join_time": {"$gte": seven_days_ago},
                        "leave_time": {"$ne": None}
                    }
                },
                {
                    "$group": {
                        "_id": "$user_id",
                        "username": {"$first": "$username"},
                        "total_duration": {"$sum": "$duration"}
                    }
                },
                {
                    "$sort": {
                        "total_duration": -1
                    }
                }
            ]
            cursor = self.sessions.aggregate(pipeline)
            results = []
            for doc in cursor:
                results.append({
                    "user_id": doc["_id"],
                    "username": doc["username"],
                    "total_duration": doc["total_duration"]
                })
            return results
        except Exception as e:
            logger.error(f"Failed to fetch all weekly totals from MongoDB: {e}")
            return []

    def get_range_totals(self, start_ts: int, end_ts: int) -> list:
        try:
            pipeline = [
                {
                    "$match": {
                        "join_time": {"$gte": start_ts, "$lte": end_ts},
                        "leave_time": {"$ne": None}
                    }
                },
                {
                    "$group": {
                        "_id": "$user_id",
                        "username": {"$first": "$username"},
                        "total_duration": {"$sum": "$duration"}
                    }
                },
                {
                    "$sort": {
                        "total_duration": -1
                    }
                }
            ]
            cursor = self.sessions.aggregate(pipeline)
            results = []
            for doc in cursor:
                results.append({
                    "user_id": doc["_id"],
                    "username": doc["username"],
                    "total_duration": doc["total_duration"]
                })
            return results
        except Exception as e:
            logger.error(f"Failed to fetch range totals from MongoDB: {e}")
            return []

    def add_approved_mazeret(self, user_id: str, username: str, dates: str, reason: str, approved_by: str) -> bool:
        try:
            import time
            self.mazerets.insert_one({
                "user_id": user_id,
                "username": username,
                "dates": dates,
                "reason": reason,
                "approved_by": approved_by,
                "approved_at": int(time.time())
            })
            logger.info(f"Mazeret added to DB for {username} ({user_id}) by {approved_by}")
            return True
        except Exception as e:
            logger.error(f"Failed to add approved mazeret to MongoDB: {e}")
            return False

    def get_active_mazerets(self, user_id: str) -> list:
        try:
            cursor = self.mazerets.find({"user_id": user_id})
            return list(cursor)
        except Exception as e:
            logger.error(f"Failed to fetch mazerets from MongoDB: {e}")
            return []

    def close(self):
        self.client.close()
