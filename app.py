from flask import Flask, render_template, request, jsonify, session
import boto3
import base64
import json
from datetime import datetime
import uuid

app = Flask(__name__)
# Generate this once and store it securely
app.config['SECRET_KEY'] = 'a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2'

# AWS clients (uses IAM roles)
s3 = boto3.client('s3')
rekognition = boto3.client('rekognition')
dynamodb = boto3.resource('dynamodb')

# Configuration
# AWS Configuration
BUCKET_NAME = "face-auth-storage-bucket"        # Your S3 bucket name
COLLECTION_ID = "my-face-collection"            # Your Rekognition collection
USERS_TABLE = "face-users"                      # DynamoDB table for users
LOGS_TABLE = "face-logs"                        # DynamoDB table for login/activity logs


@app.route('/')
def home():
    return render_template('home.html')

@app.route('/admin')
def admin_page():
    if not session.get('is_admin'):
        return render_template('admin_login.html')
    return render_template('admin_dashboard.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if not session.get('user_id'):
        return render_template('login.html')
    user_name = session.get('user_name', 'User')
    return render_template('dashboard.html', user_name=user_name)

@app.route('/api/admin-login', methods=['POST'])
def admin_login():
    try:
        data = request.get_json()
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        
        # Check if admin face exists
        try:
            response = rekognition.search_faces_by_image(
                CollectionId=COLLECTION_ID,
                Image={'Bytes': image_bytes},
                MaxFaces=1,
                FaceMatchThreshold=85
            )
            
            if response['FaceMatches']:
                face_id = response['FaceMatches'][0]['Face']['FaceId']
                
                # Check if this face belongs to admin
                users_table = dynamodb.Table(USERS_TABLE)
                user_response = users_table.get_item(Key={'face_id': face_id})
                
                if 'Item' in user_response and user_response['Item'].get('is_admin'):
                    session['is_admin'] = True
                    session['admin_name'] = user_response['Item']['name']
                    return jsonify({'success': True, 'message': 'Admin authenticated'})
        except:
            pass
            
        return jsonify({'success': False, 'message': 'Admin not recognized'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/create-first-admin', methods=['POST'])
def create_first_admin():
    try:
        # Check if any admin exists
        users_table = dynamodb.Table(USERS_TABLE)
        response = users_table.scan(FilterExpression='is_admin = :admin', ExpressionAttributeValues={':admin': True})
        
        if response['Items']:
            return jsonify({'success': False, 'message': 'Admin already exists'})
        
        data = request.get_json()
        image_data = data['image'].split(',')[1]
        name = data['name']
        image_bytes = base64.b64decode(image_data)
        
        # Upload to S3
        s3_key = f'admin_{name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jpg'
        s3.put_object(Bucket=BUCKET_NAME, Key=s3_key, Body=image_bytes, ContentType='image/jpeg')
        
        # Add to Rekognition collection
        response = rekognition.index_faces(
            CollectionId=COLLECTION_ID,
            Image={'Bytes': image_bytes},
            ExternalImageId=f'admin_{name}',
            MaxFaces=1,
            QualityFilter='AUTO'
        )
        
        if response['FaceRecords']:
            face_id = response['FaceRecords'][0]['Face']['FaceId']
            
            # Save admin to database
            users_table.put_item(
                Item={
                    'face_id': face_id,
                    'name': name,
                    'is_admin': True,
                    'created_at': datetime.now().isoformat(),
                    's3_key': s3_key
                }
            )
            
            return jsonify({'success': True, 'message': f'First admin {name} created successfully'})
        else:
            return jsonify({'success': False, 'message': 'No face detected'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/add-user', methods=['POST'])
def add_user():
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Admin access required'})
    
    try:
        data = request.get_json()
        image_data = data['image'].split(',')[1]
        name = data['name']
        image_bytes = base64.b64decode(image_data)
        
        # Check if face already exists
        try:
            existing = rekognition.search_faces_by_image(
                CollectionId=COLLECTION_ID,
                Image={'Bytes': image_bytes},
                MaxFaces=1,
                FaceMatchThreshold=85
            )
            if existing['FaceMatches']:
                return jsonify({'success': False, 'message': 'User already exists'})
        except:
            pass
        
        # Upload to S3
        s3_key = f'user_{name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jpg'
        s3.put_object(Bucket=BUCKET_NAME, Key=s3_key, Body=image_bytes, ContentType='image/jpeg')
        
        # Add to Rekognition collection
        response = rekognition.index_faces(
            CollectionId=COLLECTION_ID,
            Image={'Bytes': image_bytes},
            ExternalImageId=f'user_{name}',
            MaxFaces=1,
            QualityFilter='AUTO'
        )
        
        if response['FaceRecords']:
            face_id = response['FaceRecords'][0]['Face']['FaceId']
            
            # Save user to database
            users_table = dynamodb.Table(USERS_TABLE)
            users_table.put_item(
                Item={
                    'face_id': face_id,
                    'name': name,
                    'is_admin': False,
                    'account_balance': '10000.00',  # Default balance
                    'account_number': str(uuid.uuid4())[:8].upper(),
                    'created_at': datetime.now().isoformat(),
                    's3_key': s3_key
                }
            )
            
            return jsonify({'success': True, 'message': f'User {name} added successfully'})
        else:
            return jsonify({'success': False, 'message': 'No face detected'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/login', methods=['POST'])
def user_login():
    try:
        data = request.get_json()
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        
        # Search for face
        response = rekognition.search_faces_by_image(
            CollectionId=COLLECTION_ID,
            Image={'Bytes': image_bytes},
            MaxFaces=1,
            FaceMatchThreshold=85
        )
        
        if response['FaceMatches']:
            face_id = response['FaceMatches'][0]['Face']['FaceId']
            confidence = response['FaceMatches'][0]['Similarity']
            
            # Get user details
            users_table = dynamodb.Table(USERS_TABLE)
            user_response = users_table.get_item(Key={'face_id': face_id})
            
            if 'Item' in user_response:
                user = user_response['Item']
                
                # Log login attempt
                logs_table = dynamodb.Table(LOGS_TABLE)
                logs_table.put_item(
                    Item={
                        'log_id': str(uuid.uuid4()),
                        'user_id': face_id,
                        'user_name': user['name'],
                        'action': 'LOGIN_SUCCESS',
                        'confidence': str(confidence),
                        'timestamp': datetime.now().isoformat()
                    }
                )
                
                # Set session
                session['user_id'] = face_id
                session['user_name'] = user['name']
                session['is_admin'] = user.get('is_admin', False)
                
                return jsonify({
                    'success': True,
                    'message': f'Welcome {user["name"]}!',
                    'confidence': confidence,
                    'redirect': '/dashboard'
                })
        
        # Log failed attempt
        logs_table = dynamodb.Table(LOGS_TABLE)
        logs_table.put_item(
            Item={
                'log_id': str(uuid.uuid4()),
                'action': 'LOGIN_FAILED',
                'timestamp': datetime.now().isoformat(),
                'reason': 'Face not recognized'
            }
        )
        
        return jsonify({'success': False, 'message': 'Face not recognized'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/account-info')
def get_account_info():
    if not session.get('user_id'):
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    try:
        users_table = dynamodb.Table(USERS_TABLE)
        response = users_table.get_item(Key={'face_id': session['user_id']})
        
        if 'Item' in response:
            user = response['Item']
            return jsonify({
                'success': True,
                'name': user['name'],
                'account_number': user.get('account_number', 'N/A'),
                'balance': user.get('account_balance', '0.00')
            })
        
        return jsonify({'success': False, 'message': 'User not found'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/users')
def get_users():
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Admin access required'})
    
    try:
        users_table = dynamodb.Table(USERS_TABLE)
        response = users_table.scan()
        
        users = []
        for item in response['Items']:
            users.append({
                'name': item['name'],
                'is_admin': item.get('is_admin', False),
                'created_at': item['created_at'],
                'account_number': item.get('account_number', 'N/A')
            })
        
        return jsonify({'success': True, 'users': users})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out successfully'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)